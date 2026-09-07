import asyncio
import json
import re
import time
import uuid
from collections.abc import AsyncIterator

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import LoginRequest, UserSession, authenticate, get_current_user, require_admin, set_session_cookie
from .config import OLLAMA_URL, ORCHESTRATOR_URL, RAG_URL, SESSION_COOKIE, STATIC_DIR, VISION_URL

app = FastAPI(title="EyeAssist Gateway", version="0.1.0")


class ConsultationRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n"


def strip_reasoning(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)


class ReasoningFilter:
    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False

    def feed(self, text: str) -> str:
        self._buffer += text
        output = []
        while self._buffer:
            if self._inside:
                end = self._buffer.lower().find("</think>")
                if end == -1:
                    self._buffer = self._buffer[-7:]
                    return "".join(output)
                self._buffer = self._buffer[end + 8 :]
                self._inside = False
                continue

            start = self._buffer.lower().find("<think>")
            if start == -1:
                keep = max(len(self._buffer) - 7, 0)
                output.append(self._buffer[:keep])
                self._buffer = self._buffer[keep:]
                return "".join(output)

            output.append(self._buffer[:start])
            self._buffer = self._buffer[start + 7 :]
            self._inside = True
        return "".join(output)

    def flush(self) -> str:
        if self._inside:
            self._buffer = ""
            return ""
        text = self._buffer
        self._buffer = ""
        return text


def evidence_from_metadata(payload: dict) -> list[dict]:
    items = payload.get("evidence") or []
    if items:
        return items
    return [
        {"title": source, "page": None, "collection": "unknown", "distance": None}
        for source in payload.get("sources_used", [])
    ]


async def health_check(name: str, url: str, client: httpx.AsyncClient) -> dict:
    started = time.perf_counter()
    try:
        resp = await client.get(url, timeout=4)
        latency = round((time.perf_counter() - started) * 1000)
        return {"name": name, "available": resp.is_success, "status": "available" if resp.is_success else "unavailable", "latencyMs": latency}
    except Exception:
        return {"name": name, "available": False, "status": "unavailable", "latencyMs": None}


@app.post("/api/eyeassist/auth/login", response_model=UserSession)
async def login(form: LoginRequest, response: Response):
    user = authenticate(form.email, form.password)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    set_session_cookie(response, user)
    return user


@app.get("/api/eyeassist/session", response_model=UserSession)
async def session(user: UserSession = Depends(get_current_user)):
    return user


@app.delete("/api/eyeassist/session")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, httponly=True, samesite="lax")
    return {"ok": True}


@app.post("/api/eyeassist/consultations/stream")
async def consultation_stream(body: ConsultationRequest, request: Request, user: UserSession = Depends(get_current_user)):
    consultation_id = str(uuid.uuid4())
    started = time.perf_counter()

    async def events() -> AsyncIterator[str]:
        reasoning_filter = ReasoningFilter()
        yield sse({"type": "session", "consultationId": consultation_id})
        yield sse({"type": "status", "stage": "retrieval", "label": "Searching clinical evidence"})

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", f"{ORCHESTRATOR_URL}/orchestrate/stream", json={"message": body.message, "session_id": consultation_id}) as resp:
                    if resp.status_code >= 400:
                        yield sse({"type": "error", "code": "orchestrator_error", "message": "Consultation service unavailable"})
                        return
                    async for line in resp.aiter_lines():
                        if await request.is_disconnected():
                            break
                        if not line.startswith("data:"):
                            continue
                        payload = json.loads(line[5:].strip())
                        kind = payload.get("type")
                        if kind == "metadata":
                            yield sse({"type": "evidence", "items": evidence_from_metadata(payload)})
                            yield sse({"type": "status", "stage": "synthesis", "label": "Preparing clinical assessment"})
                        elif kind == "token":
                            text = reasoning_filter.feed(payload.get("content", ""))
                            if text:
                                yield sse({"type": "delta", "text": text})
                        elif kind == "done":
                            text = reasoning_filter.flush()
                            if text:
                                yield sse({"type": "delta", "text": text})
                            elapsed = round((time.perf_counter() - started) * 1000)
                            yield sse({"type": "done", "elapsedMs": elapsed})
        except asyncio.CancelledError:
            raise
        except Exception:
            yield sse({"type": "error", "code": "stream_error", "message": "Consultation stream interrupted"})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/eyeassist/health")
async def health(user: UserSession = Depends(require_admin)):
    async with httpx.AsyncClient() as client:
        checks = await asyncio.gather(
            health_check("orchestrator", f"{ORCHESTRATOR_URL}/health", client),
            health_check("rag", f"{RAG_URL}/health", client),
            health_check("vision", f"{VISION_URL}/health", client),
            health_check("ollama", f"{OLLAMA_URL}/api/tags", client),
        )
    return {"services": [{"name": "gateway", "available": True, "status": "available", "latencyMs": 0}, *checks]}


if STATIC_DIR.exists():
    app.mount("/_app", StaticFiles(directory=STATIC_DIR / "_app"), name="app-assets")
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Frontend build not found")
