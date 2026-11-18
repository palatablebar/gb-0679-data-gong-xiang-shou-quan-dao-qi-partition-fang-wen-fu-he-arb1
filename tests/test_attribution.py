import csv,io
import pytest
from app.errors import DomainError
from app.attribution import attribute,parse_tz
from app import store
def boundary_run(client): return client.post("/api/runs",json={"sample":"boundary.csv"}).get_json()
def line(run,stage,event_id): return [r for r in run["stages"][stage]["rows"] if r.get("event_id")==event_id][0]
def test_boundary_night_diverges():
    "月初夜间访问：发送方月初分区与接收方业务日落月不同"
    att=attribute({"partition":"2026-11","access_time":"2026-12-01T00:30:00+08:00","note":"月初夜间"},"+08:00")
    assert att["diverged"] and att["sender_partition"]=="2026-11" and att["receiver_partition"]=="2026-12"
def test_default_ruling_is_receiver():
    "裁决：差异默认按接收方地区日期重算，来源分区留作证据"
    att=attribute({"partition":"2026-11","access_time":"2026-12-01T00:30:00+08:00","note":"跨区"},"+08:00")
    assert att["decision"]=="receiver" and att["effective_partition"]=="2026-12" and att["source_partition"]=="2026-11"
def test_incomplete_explanation_when_note_blank():
    att=attribute({"partition":"2026-11","access_time":"2026-12-01T00:30:00+08:00","note":""},"+08:00")
    assert att["diverged"] and not att["complete"]
def test_historical_access_keeps_source():
    att=attribute({"partition":"2026-09","access_time":"2026-11-16T03:00:00+08:00"},"+08:00")
    assert not att["diverged"] and att["decision"]=="source" and att["effective_partition"]=="2026-09"
def test_same_month_consistent():
    att=attribute({"partition":"2026-11","access_time":"2026-11-15T10:00:00+08:00"},"+08:00")
    assert not att["diverged"] and att["complete"]
def test_receiver_tz_changes_attribution():
    row={"partition":"2026-11","access_time":"2026-12-01T00:30:00+08:00"}
    assert attribute(row,"UTC")["diverged"] is False and attribute(row,"+08:00")["diverged"] is True
def test_parse_tz_rejects_bad():
    with pytest.raises(DomainError): parse_tz("Mars/Olympus")
def test_unique_review_version_per_access(client):
    run=boundary_run(client)
    atts=client.get(f"/api/runs/{run['run_id']}/attributions").get_json()["attributions"]
    assert len(atts)==4 and len({a["event_id"] for a in atts})==4 and all(a["version"]==1 for a in atts)
def test_rerun_adds_no_review_version(client):
    a=boundary_run(client);b=boundary_run(client)
    assert a["run_id"]==b["run_id"]
    body=client.get(f"/api/runs/{a['run_id']}/attributions").get_json()
    assert len(body["attributions"])==4 and all(x["version"]==1 for x in body["attributions"]) and body["history"]==[]
def test_authorization_follows_receiver_decision(client):
    run=boundary_run(client);detail=client.get("/api/runs/"+run["run_id"]).get_json()
    row=line(detail,4,"10001")
    assert row["partition"]=="2026-12" and row["effect"]=="deny" and row["violation"]=="越权放行"
    assert row["attribution"]["source_partition"]=="2026-11"
def test_reconciliation_and_seal_follow_decision(client):
    run=boundary_run(client);detail=client.get("/api/runs/"+run["run_id"]).get_json()
    row=line(detail,5,"10001")
    assert row["expected"]=="0" and row["status"]=="差异"
    metrics=detail["stages"][6]["metrics"]
    assert metrics["ready"] is False and metrics["evidence_paused"]==1 and metrics["attribution_reviews"]==4 and metrics["attribution_diverged"]==2
def test_evidence_paused_until_explanation_complete(client):
    run=boundary_run(client);uid=run["run_id"]
    r=client.get(f"/api/runs/{uid}/archive")
    assert r.status_code==409 and r.get_json()["code"]=="EVIDENCE_PAUSED"
    s=client.post(f"/api/runs/{uid}/attributions/10002",json={"version":1,"decision":"receiver","explanation":"月初夜间跨区，按接收方业务日归档"})
    assert s.status_code==200
    assert client.get(f"/api/runs/{uid}/archive").status_code==200
def test_switch_interrupted_keeps_old_version(client):
    run=boundary_run(client);uid=run["run_id"]
    assert client.post(f"/api/runs/{uid}/attributions/10001",json={"version":9,"decision":"source"}).status_code==409
    body=client.get(f"/api/runs/{uid}/attributions").get_json()
    row=[a for a in body["attributions"] if a["event_id"]=="10001"][0]
    assert row["version"]==1 and row["decision"]=="receiver" and body["history"]==[]
def test_switch_archives_old_version_and_source_evidence(client):
    run=boundary_run(client);uid=run["run_id"]
    r=client.post(f"/api/runs/{uid}/attributions/10001",json={"version":1,"decision":"source","explanation":"与发送方确认沿用来源"})
    assert r.status_code==200
    body=client.get(f"/api/runs/{uid}/attributions").get_json()
    row=[a for a in body["attributions"] if a["event_id"]=="10001"][0]
    assert row["version"]==2 and row["decision"]=="source"
    old=body["history"][0]
    assert old["version"]==1 and old["decision"]=="receiver" and old["source_partition"]=="2026-11" and old["receiver_partition"]=="2026-12"
    detail=client.get(f"/api/runs/{uid}").get_json()
    assert line(detail,4,"10001")["partition"]=="2026-11" and line(detail,4,"10001")["violation"]=="一致"
def test_export_reflects_effective_partition(client):
    run=boundary_run(client);uid=run["run_id"]
    client.post(f"/api/runs/{uid}/attributions/10002",json={"version":1,"decision":"receiver","explanation":"月初夜间跨区"})
    r=client.get(f"/api/runs/{uid}/archive")
    assert r.status_code==200
    rows=list(csv.reader(io.StringIO(r.data.decode("utf-8-sig"))))
    evidence=[x[6] for x in rows[1:] if '"event_id": "10001"' in x[6]][0]
    assert '"partition": "2026-12"' in evidence and '"source_partition": "2026-11"' in evidence
def test_existing_sample_has_no_divergence(client):
    run=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()
    body=client.get(f"/api/runs/{run['run_id']}/attributions").get_json()
    assert body["attributions"] and not any(a["diverged"] for a in body["attributions"])
    assert client.get(f"/api/runs/{run['run_id']}/archive").status_code==200
def test_receiver_tz_parameter_separates_batches(client):
    a=client.post("/api/runs",json={"sample":"boundary.csv"}).get_json()
    b=client.post("/api/runs",json={"sample":"boundary.csv","parameters":{"receiver_tz":"UTC"}}).get_json()
    assert a["run_id"]!=b["run_id"]
    atts=client.get(f"/api/runs/{b['run_id']}/attributions").get_json()["attributions"]
    assert not any(x["diverged"] for x in atts)
def test_attribution_missing_run_404(client):
    assert client.get("/api/runs/missing/attributions").status_code==404
    assert client.post("/api/runs/missing/attributions/1",json={"version":1,"decision":"source"}).status_code==404
def test_bad_attribution_decision_rejected(client):
    run=boundary_run(client)
    assert client.post(f"/api/runs/{run['run_id']}/attributions/10001",json={"version":1,"decision":"maybe"}).status_code==422
