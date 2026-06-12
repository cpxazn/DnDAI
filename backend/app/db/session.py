from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def initialize_database(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with connect(database_path) as connection:
        connection.executescript(schema_sql)
        _run_lightweight_migrations(connection)
        connection.commit()


def _run_lightweight_migrations(connection: sqlite3.Connection) -> None:
    _ensure_columns(
        connection,
        table="characters",
        columns={
            "proficiency_bonus": "INTEGER NOT NULL DEFAULT 2",
            "ability_modifiers_json": "TEXT NOT NULL DEFAULT '{}'",
            "equipped_weapon_json": "TEXT NOT NULL DEFAULT '{}'",
            "weapon_loadout_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )
    _ensure_columns(
        connection,
        table="combat_encounters",
        columns={
            "winning_side": "TEXT",
            "outcome_summary": "TEXT",
        },
    )
    _ensure_columns(
        connection,
        table="combatants",
        columns={
            "base_armor_class": "INTEGER",
            "base_speed": "INTEGER",
            "speed": "INTEGER",
            "saving_throw_bonuses_json": "TEXT NOT NULL DEFAULT '{}'",
            "effects_json": "TEXT NOT NULL DEFAULT '[]'",
        },
    )


def _ensure_columns(connection: sqlite3.Connection, *, table: str, columns: dict[str, str]) -> None:
    existing = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, ddl in columns.items():
        if name in existing:
            continue
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


@contextmanager
def get_connection(database_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(database_path)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()
