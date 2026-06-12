from __future__ import annotations

from sqlite3 import Connection, Row

from backend.app.services.utils import json_dumps, json_loads, utc_now


def add_item(
    connection: Connection,
    *,
    campaign_id: int,
    character_id: str,
    item_name: str,
    quantity: int = 1,
    details: dict | None = None,
) -> bool:
    normalized_name = item_name.strip()
    if not normalized_name or quantity <= 0:
        return False

    row = connection.execute(
        """
        SELECT id, quantity, details_json
        FROM inventory_items
        WHERE character_id = ? AND name = ?
        """,
        (character_id, normalized_name),
    ).fetchone()
    if row is None:
        timestamp = utc_now()
        connection.execute(
            """
            INSERT INTO inventory_items (
              campaign_id, character_id, name, quantity, details_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                character_id,
                normalized_name,
                quantity,
                json_dumps(details or {}),
                timestamp,
                timestamp,
            ),
        )
        _sync_inventory_highlights(connection, character_id)
        return True

    merged_details = json_loads(row["details_json"], {})
    if details:
        merged_details.update(details)
    connection.execute(
        """
        UPDATE inventory_items
        SET quantity = ?, details_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (int(row["quantity"]) + quantity, json_dumps(merged_details), utc_now(), row["id"]),
    )
    _sync_inventory_highlights(connection, character_id)
    return True


def remove_item(
    connection: Connection,
    *,
    character_id: str,
    item_name: str,
    quantity: int = 1,
) -> bool:
    normalized_name = item_name.strip()
    if not normalized_name or quantity <= 0:
        return False

    row = connection.execute(
        """
        SELECT id, quantity
        FROM inventory_items
        WHERE character_id = ? AND name = ?
        """,
        (character_id, normalized_name),
    ).fetchone()
    if row is None or int(row["quantity"]) < quantity:
        return False

    remaining = int(row["quantity"]) - quantity
    if remaining == 0:
        connection.execute("DELETE FROM inventory_items WHERE id = ?", (row["id"],))
    else:
        connection.execute(
            """
            UPDATE inventory_items
            SET quantity = ?, updated_at = ?
            WHERE id = ?
            """,
            (remaining, utc_now(), row["id"]),
        )
    _sync_inventory_highlights(connection, character_id)
    return True


def _sync_inventory_highlights(connection: Connection, character_id: str, limit: int = 5) -> None:
    rows = connection.execute(
        """
        SELECT name, quantity
        FROM inventory_items
        WHERE character_id = ?
        ORDER BY quantity DESC, name ASC
        LIMIT ?
        """,
        (character_id, limit),
    ).fetchall()
    highlights = [
        _format_highlight(row)
        for row in rows
    ]
    connection.execute(
        """
        UPDATE characters
        SET inventory_highlights_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (json_dumps(highlights), utc_now(), character_id),
    )


def _format_highlight(row: Row) -> str:
    quantity = int(row["quantity"])
    name = str(row["name"])
    return f"{name} x{quantity}" if quantity > 1 else name
