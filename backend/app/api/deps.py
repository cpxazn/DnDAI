from __future__ import annotations

from collections.abc import Iterator
from sqlite3 import Connection

from fastapi import Depends, HTTPException

from backend.app.core.config import Settings, get_settings
from backend.app.db.session import get_connection


def get_app_settings() -> Settings:
    return get_settings()


def get_db(settings: Settings = Depends(get_app_settings)) -> Iterator[Connection]:
    with get_connection(settings.database_file) as connection:
        yield connection


def ensure_exists(connection: Connection, table: str, entity_id: int | str) -> None:
    row = connection.execute(f"SELECT 1 FROM {table} WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{table[:-1].capitalize()} not found.")
