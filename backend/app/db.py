"""SQLite 访问层：WAL、幂等建表、读连接按线程隔离、写连接单实例加锁。

写并发策略：所有写入走同一个连接 + 一把可重入锁（MQTT 线程与 HTTP 线程共用），
读走 thread-local 连接。WAL 允许读写并行，锁只序列化写者，避免 "database is locked"。
"""
from __future__ import annotations

import sqlite3
import threading

from . import config
from .timeutil import now_iso

# 契约第 4 节 DDL，原样照抄。
DDL = """
CREATE TABLE IF NOT EXISTS devices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  plot_code TEXT NOT NULL, plot_name TEXT, type TEXT NOT NULL,
  location TEXT, status TEXT DEFAULT 'online', last_seen TEXT,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS telemetry (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_code TEXT NOT NULL, ts TEXT NOT NULL,
  temperature REAL, humidity REAL, soil_moisture REAL, soil_temp REAL,
  battery REAL, raw TEXT);
CREATE INDEX IF NOT EXISTS idx_telemetry_device_ts ON telemetry(device_code, ts);
CREATE INDEX IF NOT EXISTS idx_telemetry_ts ON telemetry(ts);
CREATE TABLE IF NOT EXISTS ai_chat (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT, question TEXT NOT NULL, answer TEXT,
  model TEXT, degraded INTEGER DEFAULT 0, latency_ms INTEGER,
  prompt_tokens INTEGER, completion_tokens INTEGER, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_ai_chat_created ON ai_chat(created_at DESC);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_code TEXT NOT NULL, metric TEXT NOT NULL, value REAL, threshold REAL,
  level TEXT, message TEXT, acked INTEGER DEFAULT 0, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at DESC);
"""

_write_lock = threading.RLock()
_write_conn: sqlite3.Connection | None = None
_local = threading.local()


def _configure(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _new_conn() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _configure(sqlite3.connect(str(config.DB_PATH), check_same_thread=False, timeout=30))


def _read_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _new_conn()
        _local.conn = conn
    return conn


def write_conn() -> sqlite3.Connection:
    global _write_conn
    if _write_conn is None:
        _write_conn = _new_conn()
    return _write_conn


def close_all() -> None:
    global _write_conn
    with _write_lock:
        if _write_conn is not None:
            _write_conn.close()
            _write_conn = None
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


# ---------------- 通用助手 ----------------
def query(sql: str, params: tuple = ()) -> list[dict]:
    return [dict(row) for row in _read_conn().execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    row = _read_conn().execute(sql, params).fetchone()
    return dict(row) if row else None


def execute(sql: str, params: tuple = ()) -> int:
    """写入（事务提交），返回受影响行数。"""
    with _write_lock:
        conn = write_conn()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount


def insert(sql: str, params: tuple = ()) -> int:
    """写入并返回 lastrowid。"""
    with _write_lock:
        conn = write_conn()
        cur = conn.execute(sql, params)
        conn.commit()
        return int(cur.lastrowid or 0)


def executemany(sql: str, rows: list[tuple]) -> int:
    if not rows:
        return 0
    with _write_lock:
        conn = write_conn()
        cur = conn.executemany(sql, rows)
        conn.commit()
        return cur.rowcount


def init_db() -> None:
    with _write_lock:
        conn = write_conn()
        conn.executescript(DDL)
        conn.commit()
    seed_devices()


def seed_devices() -> None:
    """幂等写入契约第 3 节的 4 台设备（已存在则刷新元数据，不动 last_seen）。"""
    created = now_iso()
    rows = [
        (
            d["device_code"], d["name"], d["plot_code"], d["plot_name"],
            d["type"], d["location"], created,
        )
        for d in config.DEVICES
    ]
    executemany(
        """INSERT INTO devices (device_code, name, plot_code, plot_name, type, location, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(device_code) DO UPDATE SET
             name=excluded.name, plot_code=excluded.plot_code, plot_name=excluded.plot_name,
             type=excluded.type, location=excluded.location""",
        rows,
    )


# ---------------- 业务查询助手 ----------------
def insert_telemetry(device_code: str, ts: str, metrics: dict, raw: str | None) -> int:
    return insert(
        """INSERT INTO telemetry (device_code, ts, temperature, humidity, soil_moisture, soil_temp, battery, raw)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            device_code, ts,
            metrics.get("temperature"), metrics.get("humidity"),
            metrics.get("soil_moisture"), metrics.get("soil_temp"),
            metrics.get("battery"), raw,
        ),
    )


def touch_device(device_code: str, ts: str) -> None:
    execute(
        "UPDATE devices SET last_seen = ?, status = 'online' WHERE device_code = ?",
        (ts, device_code),
    )


def latest_telemetry(device_code: str) -> dict | None:
    return query_one(
        """SELECT ts, temperature, humidity, soil_moisture, soil_temp, battery
           FROM telemetry WHERE device_code = ? ORDER BY ts DESC, id DESC LIMIT 1""",
        (device_code,),
    )


def list_devices() -> list[dict]:
    return query("SELECT * FROM devices ORDER BY device_code")


def purge_old_telemetry() -> int:
    """按 TELEMETRY_RETENTION_DAYS 清理过期遥测（契约第 2 节的保留期参数）。"""
    from .timeutil import cutoff_iso
    return execute("DELETE FROM telemetry WHERE ts < ?", (cutoff_iso(config.TELEMETRY_RETENTION_DAYS * 24),))


def db_ok() -> bool:
    try:
        _read_conn().execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False
