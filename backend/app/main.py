from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.api import chat, combat, health, llm, campaigns, sessions, characters, party, dice, memory
from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging
from backend.app.db.session import initialize_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging()
    initialize_database(settings.database_file)
    yield


app = FastAPI(title="myDnD", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(campaigns.router)
app.include_router(sessions.router)
app.include_router(characters.router)
app.include_router(party.router)
app.include_router(dice.router)
app.include_router(combat.router)
app.include_router(llm.router)
app.include_router(memory.router)
app.include_router(chat.router)
