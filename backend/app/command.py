"""指令闭环（V2_PLAN.md 第 9 节）：落库 + MQTT QoS1 下发 + 回执驱动状态流转。

状态机：dispatched -> executed（收到 agri/command_ack 回执）
                  -> failed（回执 status=failed）
                  -> timeout（COMMAND_ACK_TIMEOUT_SECONDS 内无回执，后台清扫）
"""
from __future__ import annotations

import json
import logging
import time
import uuid

from . import config, db
from .mqtt_client import ingest
from .timeutil import now_iso

log = logging.getLogger("agri.command")


def new_command_id() -> str:
    stamp = now_iso().replace("-", "").replace(":", "").replace("+", "")[:15]
    return f"cmd_{stamp}_{uuid.uuid4().hex[:4]}"


def execute(payload: dict) -> dict:
    """POST /api/command/execute 的业务实现。MQTT 不可达也不报错（status 仍 dispatched）。"""
    command_id = new_command_id()
    plot_code = payload["plot_code"]
    device_code = payload["device_code"]
    action = payload["action"]
    params = payload.get("params") or {}
    issued_at = now_iso()
    topic = config.MQTT_COMMAND_TOPIC_TEMPLATE.format(
        plot_code=plot_code, device_code=device_code
    )
    body = {
        "command_id": command_id,
        "action": action,
        "params": params,
        "issued_at": issued_at,
    }

    published = ingest.publish(topic, body, qos=config.MQTT_COMMAND_QOS)
    detail = None if published else "MQTT 未连接，指令已落库但未真正下发"

    db.insert_command({
        "id": command_id,
        "reasoning_id": payload.get("reasoning_id"),
        "plot_code": plot_code,
        "device_code": device_code,
        "node_id": payload.get("node_id"),
        "action": action,
        "params": json.dumps(params, ensure_ascii=False),
        "topic": topic,
        "payload": json.dumps(body, ensure_ascii=False),
        "status": "dispatched",
        "ack_at": None,
        "created_at": issued_at,
    })
    log.info("指令已下发 %s -> %s (%s)", command_id, topic, action)

    return {
        "command_id": command_id,
        "topic": topic,
        "payload": body,
        "status": "dispatched",
        "published": published,
        "detail": detail,
    }


def handle_ack(plot_code: str, device_code: str, payload: dict) -> bool:
    """处理 agri/command_ack/{plot}/{device} 回执。返回是否命中了已落库的指令。"""
    command_id = str(payload.get("command_id") or "").strip()
    if not command_id:
        log.warning("回执缺少 command_id，已丢弃：%s", payload)
        return False

    ack_at = now_iso()
    status = str(payload.get("status") or "executed").strip().lower()
    if status == "failed":
        changed = db.mark_command_failed(command_id, ack_at)
    else:
        changed = db.mark_command_executed(command_id, ack_at)

    if changed:
        log.info("指令回执已落库 %s -> %s（%s/%s）", command_id, status, plot_code, device_code)
    else:
        log.info("指令回执未改变状态（可能已终态或指令不存在）：%s", command_id)
    return bool(changed)


def sweep_timeouts() -> int:
    """把超过 COMMAND_ACK_TIMEOUT_SECONDS 仍无回执的 dispatched 指令标为 timeout。"""
    from .timeutil import cutoff_iso

    seconds = float(config.COMMAND_ACK_TIMEOUT_SECONDS)
    if seconds <= 0:
        return 0
    cutoff = cutoff_iso(seconds / 3600.0)
    changed = db.expire_commands(cutoff)
    if changed:
        log.info("指令超时清扫：%s 条 dispatched -> timeout（阈值 %ss）", changed, seconds)
    return changed


def history(limit: int) -> dict:
    limit = max(1, min(int(limit), config.COMMAND_HISTORY_LIMIT))
    rows = db.list_commands(limit)
    items = []
    for row in rows:
        items.append({
            "command_id": row["id"],
            "reasoning_id": row.get("reasoning_id"),
            "plot_code": row["plot_code"],
            "device_code": row["device_code"],
            "node_id": row.get("node_id"),
            "action": row["action"],
            "params": _loads(row.get("params")),
            "topic": row["topic"],
            "payload": _loads(row.get("payload")),
            "status": row["status"],
            "ack_at": row.get("ack_at"),
            "created_at": row["created_at"],
            "detail": _status_detail(row),
        })
    return {"total": db.count_commands(), "items": items}


def _loads(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


_STATUS_CN = {
    "dispatched": "已下发，等待模拟器回执",
    "executed": "模拟器已执行并回执",
    "failed": "模拟器执行失败",
    "timeout": f"超时未收到回执",
}


def _status_detail(row: dict) -> str:
    status = row.get("status")
    if status == "timeout":
        return f"超过 {config.COMMAND_ACK_TIMEOUT_SECONDS}s 未收到回执，已标记 timeout"
    return _STATUS_CN.get(status, status or "")
