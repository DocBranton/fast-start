import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.databricks import DatabricksClient


def sse_events(text: str):
    out = []
    for block in text.strip().split("\n\n"):
        ev = block.split("\n")[0].removeprefix("event: ")
        data = json.loads(block.split("\n")[1].removeprefix("data: "))
        out.append((ev, data))
    return out


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setattr(main.settings, "mock", True)
    with TestClient(main.app) as c:
        yield c


def test_health(mock_client):
    assert mock_client.get("/healthz").json() == {"status": "ok"}
    assert mock_client.get("/").status_code == 200


def test_mock_chat_streams(mock_client):
    r = mock_client.post("/api/chat", json={"model": "gpt-5-4", "messages": [{"role": "user", "content": "hi"}]})
    events = sse_events(r.text)
    assert events[-1][0] == "done"
    assert "[mock]" in "".join(d["text"] for e, d in events if e == "delta")


def test_rejects_unknown_model(mock_client):
    r = mock_client.post("/api/chat", json={"model": "databricks-genie", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 400


async def test_databricks_stream_and_models(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "adb-1.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
    s = Settings()
    seen = {}

    def handler(req: httpx.Request):
        seen.setdefault("auth", req.headers["authorization"])
        if req.url.path == "/api/2.0/serving-endpoints":
            return httpx.Response(200, json={"endpoints": [
                {"name": "gpt-5-4", "state": {"ready": "READY"}},
                {"name": "grok-4-6", "state": {"ready": "NOT_READY"}},
                {"name": "databricks-genie", "state": {"ready": "READY"}},
            ]})
        assert req.url.path == "/serving-endpoints/gpt-5-4/invocations"
        body = json.loads(req.content)
        assert body["stream"] is True and body["messages"][0]["role"] == "system"
        chunks = [{"choices": [{"delta": {"content": "Hello"}}]},
                  {"choices": [{"delta": {"content": [{"type": "text", "text": " world"}]}}]}]
        sse = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    c = DatabricksClient(s)
    c.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    models = await c.list_models()
    assert models == [{"id": "gpt-5-4", "ready": True}, {"id": "grok-4-6", "ready": False}]
    text = "".join([p async for p in c.stream_chat("gpt-5-4", [{"role": "user", "content": "hi"}])])
    assert text == "Hello world"
    assert seen["auth"] == "Bearer dapi-test"
    await c.close()
