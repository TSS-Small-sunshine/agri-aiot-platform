"""告警查询与确认（契约第 5 节）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import db, schemas

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=schemas.AlertsResponse)
def list_alerts(
    limit: int = Query(50, gt=0),
    only_unacked: bool = Query(False),
) -> schemas.AlertsResponse:
    limit = min(limit, 500)
    total = db.query_one("SELECT COUNT(*) AS c FROM alerts")["c"]
    unacked = db.query_one("SELECT COUNT(*) AS c FROM alerts WHERE acked = 0")["c"]

    sql = "SELECT * FROM alerts"
    params: list = []
    if only_unacked:
        sql += " WHERE acked = 0"
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)

    items = [schemas.AlertItem(**row) for row in db.query(sql, tuple(params))]
    return schemas.AlertsResponse(total=int(total), unacked=int(unacked), items=items)


@router.post("/{alert_id}/ack", response_model=schemas.OkAck)
def ack_alert(alert_id: int) -> schemas.OkAck:
    row = db.query_one("SELECT id FROM alerts WHERE id = ?", (alert_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="alert not found")
    db.execute("UPDATE alerts SET acked = 1 WHERE id = ?", (alert_id,))
    return schemas.OkAck(ok=True, id=alert_id)
