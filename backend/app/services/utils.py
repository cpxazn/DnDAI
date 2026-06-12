from __future__ import annotations

import json
from datetime import UTC, datetime
from sqlite3 import Row
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def row_to_dict(row: Row) -> dict[str, Any]:
    return dict(row)
