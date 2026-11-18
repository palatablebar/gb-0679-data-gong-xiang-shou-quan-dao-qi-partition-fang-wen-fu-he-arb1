import time
from app.config import ROOT,MODULES
from app.errors import DomainError
from app.values import scalar
from app.manifest import digest,manifest
from app.attribution import view as attribution_view
from app import store
from app.modules.m1_accesses.rules import evaluate as stage1
from app.modules.m2_resources.rules import evaluate as stage2
from app.modules.m3_grants.rules import evaluate as stage3
from app.modules.m4_conflicts.rules import evaluate as stage4
from app.modules.m5_partitions.rules import evaluate as stage5
from app.modules.m6_audit.rules import evaluate as stage6
from app.modules.m7_seals.rules import evaluate as stage7
STAGES=[stage1,stage2,stage3,stage4,stage5,stage6,stage7]
def load_sample(name):
    if name not in {"dirty.csv","clean.csv","legacy.csv","boundary.csv"}: raise DomainError("BAD_SAMPLE","样例不存在",404)
    return (ROOT/"sample_data"/name).read_bytes()
def calculate(raw,params=None,stop=6):
    params=params or {};started=time.monotonic();context={"parameters":params,"raw":raw,"quarantine":[]};stages=[];rows=[]
    for index,stage in enumerate(STAGES[:stop+1]):
        result=stage(raw if index==0 else rows,context)
        result=scalar(result);rows=result["rows"]
        context["quarantine"].extend(result.get("quarantine",[]))
        if index==0: context["intake"]=result["metrics"]
        result["cumulative_quarantine"]=list(context["quarantine"])
        context[MODULES[index][0]]=result
        stages.append(result)
    return {"run_id":digest(raw,params)[:20],"stages":stages,"manifest":manifest(raw,params,started),"parameters":params}
def execute(raw,params=None):
    result=calculate(raw,params);return store.save(result["run_id"],result)
def stage_preview(index,payload):
    if "rows" in payload and index>0:
        if not isinstance(payload["rows"],list) or any(not isinstance(row,dict) for row in payload["rows"]): raise DomainError("BAD_ROWS","记录需要对象列表")
        if not isinstance(payload.get("context",{}),dict): raise DomainError("BAD_CONTEXT","上下文需要对象")
        return scalar(STAGES[index](payload["rows"],payload.get("context",{"parameters":{},"quarantine":[]})))
    raw=payload.get("csv")
    raw=raw.encode() if isinstance(raw,str) else load_sample(payload.get("sample","dirty.csv"))
    return calculate(raw,payload.get("parameters",{}),index)["stages"][-1]
def apply_reviews(run,reviews):
    "按归属复核结论重算授权、对账与证据视图；来源分区证据保留在每行attribution中。"
    by_event={str(r["event_id"]):r for r in reviews};stages=list(run["stages"]);rows=[]
    for row in stages[1]["rows"]:
        review=by_event.get(str(row.get("event_id")))
        if review and review["decision"]=="receiver" and review["receiver_partition"]!=row.get("partition"): rows.append({**row,"partition":review["receiver_partition"],"attribution":{"source_partition":review["source_partition"]}})
        else: rows.append(dict(row))
    context={"parameters":run.get("parameters",{}),"quarantine":list(stages[1].get("cumulative_quarantine",[])),"intake":stages[0]["metrics"],MODULES[0][0]:stages[0],MODULES[1][0]:stages[1]}
    out=list(stages[:2])
    for index,stage in enumerate(STAGES[2:],2):
        result=scalar(stage(rows,context));rows=result["rows"]
        context["quarantine"].extend(result.get("quarantine",[]))
        result["cumulative_quarantine"]=list(context["quarantine"])
        context[MODULES[index][0]]=result
        out.append(result)
    for stage_result in out[4:]:
        for row in stage_result["rows"]:
            review=by_event.get(str(row.get("event_id")))
            if review: row["attribution"]=attribution_view(review)
    paused=sum(1 for r in reviews if r["diverged"] and not r["complete"])
    metrics=out[-1]["metrics"]
    metrics["ready"]=bool(metrics.get("ready",True)) and not paused
    metrics["evidence_paused"]=paused
    metrics["attribution_reviews"]=len(reviews)
    metrics["attribution_diverged"]=sum(1 for r in reviews if r["diverged"])
    return {**run,"stages":out,"attributions":reviews}
def reviewed(run_id):
    return apply_reviews(store.get(run_id),store.attributions(run_id))
