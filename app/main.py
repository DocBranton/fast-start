"""Wingman Lite: a minimal Workbench shell with the Wingman AI assistant."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import settings
from .databricks import DatabricksClient, WingmanError

log = logging.getLogger("wingman")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = DatabricksClient(settings)
    log.info("Wingman started: auth=%s models=%s", settings.auth_mode, settings.models)
    yield
    await app.state.db.close()


app = FastAPI(title="Wingman Lite", version=settings.app_version, lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")


class Message(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=20000)


class ChatRequest(BaseModel):
    model: str
    messages: list[Message] = Field(min_length=1, max_length=40)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    if settings.auth_mode == "none":
        raise HTTPException(503, "Databricks credentials missing")
    return {"status": "ready", "auth": settings.auth_mode}


@app.get("/api/config")
async def config():
    return {
        "version": settings.app_version,
        "mode": settings.auth_mode,
        "defaultModel": settings.default_model,
    }


@app.get("/api/models")
async def models():
    if settings.mock:
        return {"models": [{"id": m, "ready": True} for m in settings.models]}
    return {"models": await app.state.db.list_models()}


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _mock_stream(model: str, prompt: str):
    reply = (
        f"[mock] Wingman is running without a model connection, so this is a canned reply "
        f"from '{model}'. You asked: \"{prompt[:200]}\". Set DATABRICKS_HOST and "
        f"credentials to talk to a real endpoint."
    )
    for word in reply.split(" "):
        await asyncio.sleep(0.02)
        yield word + " "


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if req.model not in settings.models:
        raise HTTPException(400, f"Model '{req.model}' is not enabled for Wingman.")
    msgs = [m.model_dump() for m in req.messages]

    async def events():
        try:
            if settings.mock:
                source = _mock_stream(req.model, msgs[-1]["content"])
            else:
                source = app.state.db.stream_chat(req.model, msgs)
            async for piece in source:
                yield _sse("delta", {"text": piece})
            yield _sse("done", {"model": req.model})
        except WingmanError as e:
            log.warning("chat error: %s", e)
            yield _sse("error", {"message": str(e)})
        except Exception:
            log.exception("chat failed")
            yield _sse("error", {"message": "Wingman hit an unexpected error."})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")
