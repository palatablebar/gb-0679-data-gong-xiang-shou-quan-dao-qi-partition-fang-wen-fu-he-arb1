import re
from datetime import timezone,timedelta
from app.errors import DomainError
from app.values import SENTINELS,instant
DEFAULT_TZ="+08:00"
def parse_tz(text):
    t=str(text).strip().upper()
    if t in {"","Z","UTC"}: return timezone.utc
    m=re.fullmatch(r"([+-])(\d{1,2}):?(\d{2})?",t)
    if not m: raise DomainError("BAD_TIMEZONE","接收方时区需要如 +08:00 的偏移")
    hours,minutes=int(m.group(2)),int(m.group(3) or 0)
    if hours>14 or minutes>59: raise DomainError("BAD_TIMEZONE","接收方时区超出范围")
    delta=timedelta(hours=hours,minutes=minutes)
    return timezone(delta if m.group(1)=="+" else -delta)
def month_of(moment): return f"{moment.year:04d}-{moment.month:02d}"
def human_note(row):
    note=str(row.get("note","")).strip()
    return "" if note.upper() in SENTINELS else note
def attribute(row,tz_text=DEFAULT_TZ):
    "为单次共享访问推导分区归属；无法判定访问时刻时返回None。"
    moment=row.get("at") or row.get("access_time")
    if moment is None: return None
    try: utc=instant(moment)
    except DomainError: return None
    local=utc.astimezone(parse_tz(tz_text))
    source=str(row.get("attribution",{}).get("source_partition") or row.get("partition",""))
    sender,receiver=month_of(utc),month_of(local)
    diverged=source==sender and receiver!=source
    decision="receiver" if diverged else "source"
    if diverged:
        note=human_note(row);complete=bool(note)
        explanation=f"发送方月初分区{source}；接收方{tz_text}业务日{local.date().isoformat()}归属{receiver}"
        if note: explanation+=f"；说明：{note}"
    elif source==receiver: explanation="当期访问，来源分区与接收方归属一致";complete=True
    else: explanation="历史分区访问，沿用来源分区";complete=True
    return {"source_partition":source,"sender_partition":sender,"receiver_partition":receiver,"receiver_tz":tz_text,"diverged":diverged,"decision":decision,"effective_partition":receiver if decision=="receiver" else source,"explanation":explanation,"complete":complete,"version":1}
def view(review):
    "把复核记录还原为行内归属结论，授权、对账与证据统一服从。"
    return {"source_partition":review["source_partition"],"sender_partition":review["sender_partition"],"receiver_partition":review["receiver_partition"],"receiver_tz":review["receiver_tz"],"diverged":bool(review["diverged"]),"decision":review["decision"],"effective_partition":review["receiver_partition"] if review["decision"]=="receiver" else review["source_partition"],"explanation":review["explanation"],"complete":bool(review["complete"]),"version":review["version"]}
