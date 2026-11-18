import sqlite3,json
from pathlib import Path
from datetime import datetime,timezone
from app.config import DATA_DIR
from app.errors import DomainError
REVIEW_COLUMNS=["run_id","event_id","source_partition","sender_partition","receiver_partition","receiver_tz","decision","explanation","complete","diverged","version"]
HISTORY_COLUMNS=["event_id","version","decision","explanation","source_partition","receiver_partition","superseded_at"]
def connect():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA_DIR/"records.db",timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核')")
    db.execute("CREATE TABLE IF NOT EXISTS partition_reviews (run_id TEXT NOT NULL,event_id TEXT NOT NULL,source_partition TEXT NOT NULL,sender_partition TEXT NOT NULL,receiver_partition TEXT NOT NULL,receiver_tz TEXT NOT NULL,decision TEXT NOT NULL,explanation TEXT NOT NULL,complete INTEGER NOT NULL,diverged INTEGER NOT NULL,version INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(run_id,event_id))")
    db.execute("CREATE TABLE IF NOT EXISTS partition_review_history (id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,event_id TEXT NOT NULL,version INTEGER NOT NULL,decision TEXT NOT NULL,explanation TEXT NOT NULL,source_partition TEXT NOT NULL,receiver_partition TEXT NOT NULL,superseded_at TEXT NOT NULL)")
    return db
def save(run_id,payload):
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO runs(id,payload) VALUES (?,?)",(run_id,json.dumps(payload,ensure_ascii=False)))
        if len(payload.get("stages",[]))>4:
            for row in payload["stages"][4]["rows"]:
                att=row.get("attribution")
                if not att: continue
                db.execute("INSERT OR IGNORE INTO partition_reviews(run_id,event_id,source_partition,sender_partition,receiver_partition,receiver_tz,decision,explanation,complete,diverged,version) VALUES (?,?,?,?,?,?,?,?,?,?,1)",(run_id,str(row.get("event_id")),att["source_partition"],att["sender_partition"],att["receiver_partition"],att["receiver_tz"],att["decision"],att["explanation"],1 if att["complete"] else 0,1 if att["diverged"] else 0))
    return get(run_id)
def get(run_id):
    with connect() as db: row=db.execute("SELECT payload,version,decision FROM runs WHERE id=?",(run_id,)).fetchone()
    if not row: raise DomainError("NOT_FOUND","批次不存在",404)
    return {**json.loads(row[0]),"version":row[1],"decision":row[2]}
def latest():
    with connect() as db: row=db.execute("SELECT id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    return get(row[0]) if row else None
def history():
    with connect() as db: return [{"run_id":i,"version":v,"decision":d} for i,v,d in db.execute("SELECT id,version,decision FROM runs ORDER BY rowid DESC")]
def review(run_id,version,decision):
    if decision not in {"已复核","退回复核"}: raise DomainError("BAD_DECISION","复核状态无效")
    with connect() as db:
        cursor=db.execute("UPDATE runs SET version=version+1,decision=? WHERE id=? AND version=?",(decision,run_id,version))
        if cursor.rowcount!=1:
            if not db.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone(): raise DomainError("NOT_FOUND","批次不存在",404)
            raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
    return get(run_id)
def attributions(run_id):
    with connect() as db: rows=db.execute("SELECT "+",".join(REVIEW_COLUMNS)+" FROM partition_reviews WHERE run_id=? ORDER BY event_id",(run_id,)).fetchall()
    out=[]
    for row in rows:
        record=dict(zip(REVIEW_COLUMNS,row));record["complete"]=bool(record["complete"]);record["diverged"]=bool(record["diverged"]);out.append(record)
    return out
def review_history(run_id):
    with connect() as db: rows=db.execute("SELECT "+",".join(HISTORY_COLUMNS)+" FROM partition_review_history WHERE run_id=? ORDER BY id",(run_id,)).fetchall()
    return [dict(zip(HISTORY_COLUMNS,row)) for row in rows]
def attribution_paused(run_id):
    with connect() as db: row=db.execute("SELECT COUNT(*) FROM partition_reviews WHERE run_id=? AND diverged=1 AND complete=0",(run_id,)).fetchone()
    return row[0]>0
def switch_attribution(run_id,event_id,version,decision,explanation=None):
    if decision not in {"source","receiver"}: raise DomainError("BAD_DECISION","归属裁决无效")
    note=str(explanation or "").strip()
    with connect() as db:
        row=db.execute("SELECT version,decision,explanation,complete,source_partition,receiver_partition FROM partition_reviews WHERE run_id=? AND event_id=?",(run_id,event_id)).fetchone()
        if not row: raise DomainError("NOT_FOUND","复核记录不存在",404)
        old_version,old_decision,old_explanation,old_complete,source,receiver=row
        if old_version!=version: raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
        if decision==old_decision and not note: return attributions(run_id)
        db.execute("INSERT INTO partition_review_history(run_id,event_id,version,decision,explanation,source_partition,receiver_partition,superseded_at) VALUES (?,?,?,?,?,?,?,?)",(run_id,event_id,old_version,old_decision,old_explanation,source,receiver,datetime.now(timezone.utc).isoformat()))
        new_explanation=old_explanation if not note else old_explanation+"；复核说明："+note
        complete=1 if old_complete or note else 0
        cursor=db.execute("UPDATE partition_reviews SET version=version+1,decision=?,explanation=?,complete=? WHERE run_id=? AND event_id=? AND version=?",(decision,new_explanation,complete,run_id,event_id,version))
        if cursor.rowcount!=1: raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
    return attributions(run_id)
