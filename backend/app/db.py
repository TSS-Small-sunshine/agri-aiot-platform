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

# V2.0 新增 4 表（docs/V2_PLAN.md 第 3 节 DDL 原文），幂等建表。
DDL_V2 = """
CREATE TABLE IF NOT EXISTS reasoning (
  id          TEXT PRIMARY KEY,
  plot_code   TEXT NOT NULL,
  trigger     TEXT,
  prompt      TEXT NOT NULL,
  result      TEXT NOT NULL,
  source      TEXT NOT NULL,
  model       TEXT,
  latency_ms  INTEGER,
  error       TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reasoning_created ON reasoning(created_at DESC);
CREATE TABLE IF NOT EXISTS commands (
  id           TEXT PRIMARY KEY,
  reasoning_id TEXT,
  plot_code    TEXT NOT NULL,
  device_code  TEXT NOT NULL,
  node_id      TEXT,
  action       TEXT NOT NULL,
  params       TEXT,
  topic        TEXT NOT NULL,
  payload      TEXT NOT NULL,
  status       TEXT NOT NULL,
  ack_at       TEXT,
  created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_commands_created ON commands(created_at DESC);
CREATE TABLE IF NOT EXISTS weather (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  plot_code    TEXT NOT NULL,
  ts           TEXT NOT NULL,
  temperature  REAL, humidity REAL, rainfall_mm REAL,
  wind_dir     TEXT, wind_level INTEGER, condition TEXT,
  UNIQUE(plot_code, ts)
);
CREATE INDEX IF NOT EXISTS idx_weather_plot_ts ON weather(plot_code, ts DESC);
CREATE TABLE IF NOT EXISTS skus (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  category    TEXT,
  price       REAL,
  unit        TEXT,
  image       TEXT,
  stock       INTEGER,
  description TEXT,
  keywords    TEXT
);
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
        conn.executescript(DDL_V2)
        conn.commit()
    seed_devices()
    seed_skus()


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


def seed_skus() -> None:
    """幂等写入 6 条农资 SKU（V2_PLAN.md 第 3 节）。INSERT OR IGNORE：绝不覆盖用户改动。"""
    rows = [
        (
            s["id"], s["name"], s["category"], s["price"], s["unit"],
            s["image"], s["stock"], s["description"], s["keywords"],
        )
        for s in config.SKUS
    ]
    executemany(
        """INSERT OR IGNORE INTO skus
           (id, name, category, price, unit, image, stock, description, keywords)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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




# ---------------- V2：推演 ----------------
def insert_reasoning(row: dict) -> None:
    execute(
        """INSERT OR REPLACE INTO reasoning
           (id, plot_code, trigger, prompt, result, source, model, latency_ms, error, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            row["id"], row["plot_code"], row.get("trigger"), row["prompt"], row["result"],
            row["source"], row.get("model"), row.get("latency_ms"), row.get("error"),
            row["created_at"],
        ),
    )


def get_reasoning(reasoning_id: str) -> dict | None:
    return query_one("SELECT * FROM reasoning WHERE id = ?", (reasoning_id,))


def list_reasoning(limit: int) -> list[dict]:
    """轻量摘要（不含 prompt/result）。reasoning.history() 另取 result 回填数字字段。"""
    return query(
        """SELECT id, plot_code, trigger, source, model, latency_ms, error, created_at
           FROM reasoning ORDER BY created_at DESC, id DESC LIMIT ?""",
        (limit,),
    )


def count_reasoning() -> int:
    row = query_one("SELECT COUNT(*) AS c FROM reasoning")
    return int(row["c"]) if row else 0


# ---------------- V2：指令 ----------------
def insert_command(row: dict) -> None:
    execute(
        """INSERT INTO commands
           (id, reasoning_id, plot_code, device_code, node_id, action, params, topic, payload,
            status, ack_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            row["id"], row.get("reasoning_id"), row["plot_code"], row["device_code"],
            row.get("node_id"), row["action"], row.get("params"), row["topic"], row["payload"],
            row["status"], row.get("ack_at"), row["created_at"],
        ),
    )


def get_command(command_id: str) -> dict | None:
    return query_one("SELECT * FROM commands WHERE id = ?", (command_id,))


def list_commands(limit: int) -> list[dict]:
    return query(
        "SELECT * FROM commands ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
    )


def count_commands() -> int:
    row = query_one("SELECT COUNT(*) AS c FROM commands")
    return int(row["c"]) if row else 0


def mark_command_executed(command_id: str, ack_at: str) -> int:
    """回执到达：仅当仍是 dispatched 才流转，避免乱序回执覆盖终态。"""
    return execute(
        "UPDATE commands SET status = 'executed', ack_at = ? WHERE id = ? AND status = 'dispatched'",
        (ack_at, command_id),
    )


def mark_command_failed(command_id: str, ack_at: str) -> int:
    return execute(
        "UPDATE commands SET status = 'failed', ack_at = ? WHERE id = ? AND status = 'dispatched'",
        (ack_at, command_id),
    )


def expire_commands(cutoff: str) -> int:
    """把超过 COMMAND_ACK_TIMEOUT_SECONDS 仍无回执的指令标为 timeout。"""
    return execute(
        "UPDATE commands SET status = 'timeout' WHERE status = 'dispatched' AND created_at < ?",
        (cutoff,),
    )


# ---------------- V2：气象 ----------------
def insert_weather(plot_code: str, ts: str, data: dict) -> int:
    return insert(
        """INSERT OR REPLACE INTO weather
           (plot_code, ts, temperature, humidity, rainfall_mm, wind_dir, wind_level, condition)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            plot_code, ts, data.get("temperature"), data.get("humidity"),
            data.get("rainfall_mm"), data.get("wind_dir"), data.get("wind_level"),
            data.get("condition"),
        ),
    )


def latest_weather(plot_code: str) -> dict | None:
    return query_one(
        """SELECT plot_code, ts, temperature, humidity, rainfall_mm, wind_dir, wind_level, condition
           FROM weather WHERE plot_code = ? ORDER BY ts DESC, id DESC LIMIT 1""",
        (plot_code,),
    )


def list_weather(plot_code: str, limit: int) -> list[dict]:
    return query(
        """SELECT ts, temperature, humidity, rainfall_mm, wind_dir, wind_level, condition
           FROM weather WHERE plot_code = ? ORDER BY ts DESC, id DESC LIMIT ?""",
        (plot_code, limit),
    )


def latest_weather_all() -> list[dict]:
    return query(
        """SELECT w.plot_code, w.ts, w.temperature, w.humidity, w.rainfall_mm,
                  w.wind_dir, w.wind_level, w.condition
           FROM weather w
           JOIN (SELECT plot_code, MAX(ts) AS mts FROM weather GROUP BY plot_code) m
             ON m.plot_code = w.plot_code AND m.mts = w.ts
           GROUP BY w.plot_code
           ORDER BY w.plot_code"""
    )


# ---------------- V2：商城 ----------------
def list_skus(keyword: str | None = None) -> list[dict]:
    """按 keywords/name/description 模糊匹配（V2_PLAN.md 第 6 节）。"""
    if keyword:
        like = f"%{keyword.strip()}%"
        return query(
            """SELECT * FROM skus
               WHERE keywords LIKE ? OR name LIKE ? OR description LIKE ? OR category LIKE ?
               ORDER BY id""",
            (like, like, like, like),
        )
    return query("SELECT * FROM skus ORDER BY id")


def db_ok() -> bool:
    try:
        _read_conn().execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False
