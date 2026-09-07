import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from passlib.context import CryptContext


def load_app(tmp_path, monkeypatch):
    db = tmp_path / "webui.db"
    conn = sqlite3.connect(db)
    conn.execute("create table auth (id text primary key, email text, password text, active boolean)")
    conn.execute("create table user (id text primary key, name text, email text, role text, profile_image_url text)")
    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    conn.execute("insert into auth values (?,?,?,?)", ("admin-id", "admin@example.test", pwd.hash("secret"), True))
    conn.execute("insert into user values (?,?,?,?,?)", ("admin-id", "Admin", "admin@example.test", "admin", ""))
    conn.execute("insert into auth values (?,?,?,?)", ("clin-id", "clin@example.test", pwd.hash("secret"), True))
    conn.execute("insert into user values (?,?,?,?,?)", ("clin-id", "Clinician", "clin@example.test", "user", ""))
    conn.commit()
    conn.close()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("EYEASSIST_SESSION_SECRET", "test-secret")

    import importlib
    import eyeassist_gateway.auth as auth
    import eyeassist_gateway.app as gateway

    importlib.reload(auth)
    importlib.reload(gateway)
    return gateway.app


def login(client, email="admin@example.test"):
    return client.post("/api/eyeassist/auth/login", json={"email": email, "password": "secret"})


def test_login_failure(tmp_path, monkeypatch):
    client = TestClient(load_app(tmp_path, monkeypatch))
    assert client.post("/api/eyeassist/auth/login", json={"email": "admin@example.test", "password": "bad"}).status_code == 401


def test_authenticated_session(tmp_path, monkeypatch):
    client = TestClient(load_app(tmp_path, monkeypatch))
    assert login(client).status_code == 200
    assert client.get("/api/eyeassist/session").json()["role"] == "admin"


def test_unauthenticated_consultation_rejected(tmp_path, monkeypatch):
    client = TestClient(load_app(tmp_path, monkeypatch))
    assert client.post("/api/eyeassist/consultations/stream", json={"message": "dry eye"}).status_code == 403


def test_health_admin_boundary(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    admin = TestClient(app)
    clinician = TestClient(app)
    assert login(admin).status_code == 200
    assert login(clinician, "clin@example.test").status_code == 200
    assert clinician.get("/api/eyeassist/health").status_code == 403


def test_reasoning_strip():
    from eyeassist_gateway.app import ReasoningFilter, strip_reasoning

    assert strip_reasoning("visible <think>hidden</think> text") == "visible  text"
    leak_filter = ReasoningFilter()
    chunks = ["visible ", "<thi", "nk>hidden", "</think> text"]
    assert "".join(leak_filter.feed(chunk) for chunk in chunks) + leak_filter.flush() == "visible  text"


def test_gateway_normalized_sse_events(tmp_path, monkeypatch):
    load_app(tmp_path, monkeypatch)
    import eyeassist_gateway.app as gateway

    class FakeStream:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def aiter_lines(self):
            yield 'data: {"type":"metadata","evidence":[{"title":"AAO","page":12,"collection":"glaucoma","distance":0.2}]}'
            yield 'data: {"type":"token","content":"Assessment "}'
            yield 'data: {"type":"token","content":"<think>hidden</think>visible"}'
            yield 'data: {"type":"done","total_time_ms":9}'

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, *args, **kwargs):
            return FakeStream()

    monkeypatch.setattr(gateway.httpx, "AsyncClient", FakeClient)

    client = TestClient(gateway.app)
    assert login(client).status_code == 200
    text = client.post("/api/eyeassist/consultations/stream", json={"message": "glaucoma?"}).text
    assert '"type":"session"' in text
    assert '"type":"evidence"' in text
    events = [
        json.loads(part.split("data: ", 1)[1])
        for part in text.split("\n\n")
        if part.startswith("data: ")
    ]
    assert "".join(event.get("text", "") for event in events if event["type"] == "delta") == "Assessment visible"
    assert "hidden" not in text
    assert '"type":"done"' in text
