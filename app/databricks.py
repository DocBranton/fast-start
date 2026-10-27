"""Thin client for Databricks Model Serving (OpenAI-compatible chat API)."""
import asyncio
import json
import time
from typing import AsyncIterator

import httpx

from .config import Settings


class WingmanError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class DatabricksClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self._token: str | None = None
        self._token_expiry = 0.0
        self._lock = asyncio.Lock()
        self._models_cache: tuple[float, list[dict]] | None = None
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(settings.request_timeout, connect=10))

    async def close(self) -> None:
        await self.http.aclose()

    # ---------- auth ----------
    async def _bearer(self) -> str:
        if self.s.databricks_token:
            return self.s.databricks_token
        if not (self.s.client_id and self.s.client_secret):
            raise WingmanError("No Databricks credentials configured.", 500)
        async with self._lock:
            if self._token and time.time() < self._token_expiry - 60:
                return self._token
            resp = await self.http.post(
                f"{self.s.databricks_host}/oidc/v1/token",
                data={"grant_type": "client_credentials", "scope": "all-apis"},
                auth=(self.s.client_id, self.s.client_secret),
            )
            if resp.status_code != 200:
                raise WingmanError(f"OAuth token request failed ({resp.status_code}).", 502)
            body = resp.json()
            self._token = body["access_token"]
            self._token_expiry = time.time() + int(body.get("expires_in", 3600))
            return self._token

    async def _headers(self) -> dict:
        return {"Authorization": f"Bearer {await self._bearer()}"}

    # ---------- models ----------
    async def list_models(self) -> list[dict]:
        """Allowlisted chat endpoints, with readiness from the workspace when available."""
        allow = self.s.models
        if not self.s.discover_models:
            return [{"id": m, "ready": None} for m in allow]
        if self._models_cache and time.time() - self._models_cache[0] < 300:
            return self._models_cache[1]
        try:
            resp = await self.http.get(
                f"{self.s.databricks_host}/api/2.0/serving-endpoints",
                headers=await self._headers(),
            )
            resp.raise_for_status()
            found = {}
            for ep in resp.json().get("endpoints", []):
                ready = (ep.get("state") or {}).get("ready") == "READY"
                found[ep.get("name")] = ready
            models = [{"id": m, "ready": found.get(m)} for m in allow if m in found]
            if not models:  # endpoints not visible to this identity; fall back to allowlist
                models = [{"id": m, "ready": None} for m in allow]
        except (httpx.HTTPError, WingmanError):
            models = [{"id": m, "ready": None} for m in allow]
        self._models_cache = (time.time(), models)
        return models

    # ---------- chat ----------
    def _check_model(self, model: str) -> None:
        if model not in self.s.models:
            raise WingmanError(f"Model '{model}' is not enabled for Wingman.", 400)

    def _payload(self, model: str, messages: list[dict], stream: bool) -> dict:
        return {
            "model": model,
            "messages": [{"role": "system", "content": self.s.system_prompt}, *messages],
            "max_tokens": self.s.max_tokens,
            "temperature": self.s.temperature,
            "stream": stream,
        }

    def _url(self, model: str) -> str:
        return f"{self.s.databricks_host}/serving-endpoints/{model}/invocations"

    async def stream_chat(self, model: str, messages: list[dict]) -> AsyncIterator[str]:
        self._check_model(model)
        async with self.http.stream(
            "POST", self._url(model), headers=await self._headers(),
            json=self._payload(model, messages, stream=True),
        ) as resp:
            if resp.status_code != 200:
                detail = (await resp.aread()).decode(errors="replace")[:300]
                raise WingmanError(f"{model} returned {resp.status_code}: {detail}", 502)
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                for choice in chunk.get("choices", []):
                    text = _text((choice.get("delta") or {}).get("content"))
                    if text:
                        yield text


def _text(content) -> str:
    """Content may be a string or a list of parts (some providers return parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""
