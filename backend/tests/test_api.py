from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from dynamical.api.app import create_app
from dynamical.ingest.pipeline import Pipeline
from fake_backend import FakeBackend
from dynamical.demo import CANNED
from test_pipeline import ALL


@pytest.fixture
def client(db, settings, load):
    Pipeline(db, settings, FakeBackend(CANNED)).ingest([load(n) for n in ALL])
    plan = [("get_events", {"start_date": "2026-10-28"})]
    app = create_app(settings=settings, db=db, backend=FakeBackend(CANNED, chat_plan=plan), background=False)
    with TestClient(app) as c:
        yield c


def test_status(client):
    data = client.get("/api/status").json()
    assert data["llm"]["enabled"] is True
    assert data["counts"]["events"]["confirmed"] == 7
    assert data["gmail"]["authorized"] is False


def test_events_range_and_conflicts(client):
    r = client.get("/api/events", params={"from": "2026-10-12T00:00:00-04:00", "to": "2026-11-01T00:00:00-04:00"})
    assert r.status_code == 200
    events = r.json()
    assert len(events) == 8  # seven confirmed plus one proposed
    assert events[0]["title"] == "CS 419 Project Sync"
    assert events[-1]["status"] == "proposed"
    assert events[0]["relationship"] == "invited"
    assert events[0]["source_subject"].startswith("Invitation:")

    # A manual block on top of the exam shows up as a conflict on both.
    exam = next(e for e in events if e["kind"] == "exam")
    r = client.post("/api/events", json={"title": "Study DP", "start": exam["start"], "end": exam["end"], "kind": "study"})
    assert r.status_code == 201
    block = r.json()
    assert block["tentative"] is True and block["source"] == "manual"
    r = client.get("/api/conflicts", params={"from": "2026-10-28T00:00:00-04:00", "to": "2026-10-29T00:00:00-04:00"})
    conflicts = r.json()
    assert len(conflicts) == 1 and conflicts[0]["severity"] == "soft"
    r = client.get(f"/api/events/{exam['id']}")
    assert block["id"] in r.json()["conflicts"]

    r = client.patch(f"/api/events/{block['id']}", json={"end": exam["start"]})
    assert r.status_code == 422  # end before start
    assert client.delete(f"/api/events/{block['id']}").status_code == 204
    assert client.get(f"/api/events/{block['id']}").status_code == 404


def test_deleting_an_email_event_rejects_it(client):
    events = client.get("/api/events", params={"from": "2026-10-12T00:00:00Z", "to": "2026-11-01T00:00:00Z"}).json()
    dinner = next(e for e in events if e["title"] == "Dinner with Priya")
    assert client.delete(f"/api/events/{dinner['id']}").status_code == 204
    r = client.get(f"/api/events/{dinner['id']}")
    assert r.status_code == 200 and r.json()["status"] == "rejected"


def test_free_time_and_digest(client):
    r = client.get("/api/free", params={"date": "2026-10-28", "min_minutes": 60})
    assert r.status_code == 200
    slots = r.json()
    assert slots and all(s["minutes"] >= 60 for s in slots)
    # The exam runs 8:40 PM to 10:00 PM local. The first slot ends when it starts,
    # and one more hour is free after it before the day ends at 11 PM.
    exam_start = datetime(2026, 10, 29, 0, 40, tzinfo=timezone.utc)
    exam_end = datetime(2026, 10, 29, 2, 0, tzinfo=timezone.utc)
    parsed = [(datetime.fromisoformat(s["start"].replace("Z", "+00:00")), datetime.fromisoformat(s["end"].replace("Z", "+00:00"))) for s in slots]
    assert parsed[0][1] == exam_start
    assert all(end <= exam_start or start >= exam_end for start, end in parsed)
    assert len(slots) == 2 and slots[-1]["minutes"] == 60

    r = client.get("/api/events", params={"from": "2026-10-28T00:00:00Z", "to": "2026-10-30T00:00:00Z"})
    exam = next(e for e in r.json() if e["kind"] == "exam")
    r = client.get(f"/api/events/{exam['id']}/suggest", params={"minutes": 120})
    assert r.status_code == 200
    suggestions = r.json()["suggestions"]
    assert sum(sg["minutes"] for sg in suggestions) == 120 or suggestions == []

    digest = client.get("/api/digest", params={"scope": "week", "date": "2026-10-26"}).json()
    assert digest["scope"] == "week" and len(digest["days"]) == 7
    titles = [e["title"] for d in digest["days"] for e in d["events"]]
    assert "CS 211 Midterm 2" in titles
    assert "CS 211 Midterm 2" in [t["title"] for d in digest["days"] for t in d["events"]]


def test_tasks_crud(client):
    r = client.get("/api/tasks")
    assert len(r.json()) == 3
    r = client.post("/api/tasks", json={"title": "Buy notebook", "due": "2026-10-16T12:00:00"})
    assert r.status_code == 201
    task = r.json()
    due = datetime.fromisoformat(task["due"].replace("Z", "+00:00"))
    assert due == datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)  # noon New York
    r = client.patch(f"/api/tasks/{task['id']}", json={"status": "done"})
    assert r.json()["status"] == "done"
    assert len(client.get("/api/tasks").json()) == 3
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204


def test_chat_round_trip(client):
    r = client.post("/api/chat", json={"message": "what do I have on Oct 28?"})
    assert r.status_code == 200
    reply = r.json()
    assert reply["role"] == "assistant"
    assert "CS 211 Midterm 2" in reply["content"]
    history = client.get("/api/chat").json()
    assert [h["role"] for h in history] == ["user", "assistant"]
    assert client.delete("/api/chat").status_code == 204
    assert client.get("/api/chat").json() == []


def test_messages_and_alerts(client):
    messages = client.get("/api/messages").json()
    assert len(messages) == 9
    promo = next(m for m in messages if "12 events" in m["subject"])
    assert promo["status"] == "skipped" and promo["triage_decision"] == "skip"
    exam_mail = next(m for m in messages if "Midterm 2" in m["subject"])
    assert exam_mail["extraction"]["relationship"] == "course"
    assert len(exam_mail["event_ids"]) == 2
    alerts = client.get("/api/alerts").json()
    assert any(a["kind"] == "review" and a["count"] == 1 for a in alerts)

    proposals = client.get("/api/proposals").json()
    assert [p["title"] for p in proposals] == ["Colloquium: Verified GPU kernels in practice"]
    accepted = client.post(f"/api/proposals/{proposals[0]['id']}/accept").json()
    assert accepted["status"] == "confirmed"
    assert client.get("/api/proposals").json() == []


def test_sync_without_token_is_a_clean_400(client):
    r = client.post("/api/sync", json={})
    assert r.status_code == 400
    assert "dynamical auth" in r.json()["detail"]
