from __future__ import annotations

import json

import httpx


class LLMUnavailableError(RuntimeError):
    """Raised when the configured local LLM is unavailable."""


class LLMClient:
    def __init__(self, base_url: str, model: str, timeout_seconds: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds

    async def complete_json(self, prompt: str) -> dict:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(f"{self._base_url}/chat/completions", json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(str(exc)) from exc

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        return json.loads(content)

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(f"{self._base_url}/models")
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(str(exc)) from exc

        payload = response.json()
        models = payload.get("data")
        if isinstance(models, list):
            result: list[str] = []
            for item in models:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    result.append(item["id"])
            return result
        return []
