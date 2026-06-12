from __future__ import annotations

import re
from dataclasses import dataclass
from sqlite3 import Connection

from backend.app.services.utils import json_loads, json_dumps, utc_now


@dataclass
class RetrievedRule:
    document_id: str
    heading_path: list[str]
    score: float
    section: str
    subsection: str | None
    text: str


def import_rules_jsonl(
    connection: Connection,
    *,
    jsonl_path: str,
    source_name: str,
    source_version: str,
    ruleset: str,
    chunker_version: str,
    source_commit_hash: str | None = None,
    notes: str | None = None,
) -> int:
    import json
    from pathlib import Path

    path = Path(jsonl_path)
    if not path.exists():
        raise FileNotFoundError(f"Rules JSONL not found: {path}")

    timestamp = utc_now()
    cursor = connection.execute(
        """
        INSERT INTO corpus_imports (
          corpus_type, source_name, source_version, source_commit_hash,
          ruleset, chunker_version, imported_at, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rules",
            source_name,
            source_version,
            source_commit_hash,
            ruleset,
            chunker_version,
            timestamp,
            notes,
        ),
    )
    import_id = int(cursor.lastrowid)

    connection.execute("DELETE FROM rules_documents")
    connection.execute("DELETE FROM rules_documents_fts")

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            record = json.loads(line)
            connection.execute(
                """
                INSERT INTO rules_documents (
                  id, import_id, doc_type, ruleset, source_file, chapter, section,
                  subsection, part, heading_path_json, tags_json, word_count, text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    import_id,
                    record["doc_type"],
                    record["ruleset"],
                    record["source_file"],
                    record.get("chapter"),
                    record["section"],
                    record.get("subsection"),
                    record.get("part"),
                    json_dumps(record["heading_path"]),
                    json_dumps(record["tags"]),
                    record["word_count"],
                    record["text"],
                ),
            )
            connection.execute(
                """
                INSERT INTO rules_documents_fts (document_id, section, subsection, text)
                VALUES (?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["section"],
                    record.get("subsection"),
                    record["text"],
                ),
            )

    return import_id


def search_rules(connection: Connection, query: str, limit: int = 4) -> list[RetrievedRule]:
    normalized_terms = re.findall(r"\w+", query.lower())
    normalized_query = " ".join(normalized_terms)
    if not normalized_terms:
        return []

    rows = connection.execute(
        """
        SELECT
          rd.id,
          rd.heading_path_json,
          rd.section,
          rd.subsection,
          rd.text,
          rd.tags_json,
          bm25(rules_documents_fts) AS base_score
        FROM rules_documents_fts rf
        JOIN rules_documents rd ON rd.id = rf.document_id
        WHERE rules_documents_fts MATCH ?
        ORDER BY bm25(rules_documents_fts)
        LIMIT 20
        """,
        (normalized_query,),
    ).fetchall()

    ranked: list[RetrievedRule] = []
    lowered = normalized_query.lower()
    for row in rows:
        heading_path = json_loads(row["heading_path_json"], [])
        tags = json_loads(row["tags_json"], [])
        score = -float(row["base_score"])
        if row["section"] and row["section"].lower() == lowered:
            score += 3.0
        if row["subsection"] and row["subsection"].lower() == lowered:
            score += 4.0
        if any(tag in lowered for tag in tags):
            score += 1.0
        ranked.append(
            RetrievedRule(
                document_id=row["id"],
                heading_path=heading_path,
                score=score,
                section=row["section"],
                subsection=row["subsection"],
                text=row["text"],
            )
        )

    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked[:limit]
