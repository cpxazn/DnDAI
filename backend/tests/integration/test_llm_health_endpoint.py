from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from backend.app.main import app
from backend.app.services.llm_client import LLMUnavailableError


class FakeLLMClientOk:
    def __init__(self, *args, **kwargs):
        pass

    async def list_models(self) -> list[str]:
        return ["ALIAS", "other-model"]


class FakeLLMClientDown:
    def __init__(self, *args, **kwargs):
        pass

    async def list_models(self) -> list[str]:
        raise LLMUnavailableError("connection refused")


def test_llm_health_ok(monkeypatch):
    from backend.app.api import llm as llm_api

    monkeypatch.setattr(llm_api, "LLMClient", FakeLLMClientOk)

    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/llm/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["data"]["status"] == "ok"
        assert "ALIAS" in payload["data"]["available_models"]

    import asyncio

    asyncio.run(run())


def test_llm_health_unavailable(monkeypatch):
    from backend.app.api import llm as llm_api

    monkeypatch.setattr(llm_api, "LLMClient", FakeLLMClientDown)

    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/llm/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["data"]["status"] == "unavailable"
        assert payload["error"]["code"] == "LLM_UNAVAILABLE"

    import asyncio

    asyncio.run(run())
