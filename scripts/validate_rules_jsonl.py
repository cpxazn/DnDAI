#!/usr/bin/env python3
"""
Validate chunked rules JSONL and print a compact report.

Example:
    python scripts/validate_rules_jsonl.py data/rules/processed/srd_5_2_1_chunks.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


REQUIRED_FIELDS = {
    "id": str,
    "doc_type": str,
    "ruleset": str,
    "source_file": str,
    "section": str,
    "heading_path": list,
    "word_count": int,
    "tags": list,
    "text": str,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Path to JSONL file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input.exists():
        raise SystemExit(f"Input not found: {args.input}")

    ids: set[str] = set()
    errors: list[str] = []
    word_counts: list[int] = []
    source_files: set[str] = set()
    examples: list[dict] = []
    lines_checked = 0

    with args.input.open("r", encoding="utf-8") as fh:
        for line_number, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line:
                continue
            lines_checked += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"Line {line_number}: invalid JSON ({exc})")
                continue

            for field, expected_type in REQUIRED_FIELDS.items():
                if field not in record:
                    errors.append(f"Line {line_number}: missing field '{field}'")
                    continue
                if not isinstance(record[field], expected_type):
                    errors.append(
                        f"Line {line_number}: field '{field}' expected {expected_type.__name__}, "
                        f"got {type(record[field]).__name__}"
                    )

            record_id = record.get("id")
            if isinstance(record_id, str):
                if record_id in ids:
                    errors.append(f"Line {line_number}: duplicate id '{record_id}'")
                ids.add(record_id)

            heading_path = record.get("heading_path")
            if isinstance(heading_path, list):
                if not heading_path:
                    errors.append(f"Line {line_number}: heading_path must not be empty")
                elif not all(isinstance(item, str) and item for item in heading_path):
                    errors.append(f"Line {line_number}: heading_path must contain non-empty strings")

            word_count = record.get("word_count")
            text = record.get("text")
            if isinstance(word_count, int):
                word_counts.append(word_count)
                if word_count <= 0:
                    errors.append(f"Line {line_number}: word_count must be positive")
            if isinstance(text, str) and not text.strip():
                errors.append(f"Line {line_number}: text must not be empty")

            source_file = record.get("source_file")
            if isinstance(source_file, str):
                source_files.add(source_file)

            if len(examples) < 5:
                examples.append(
                    {
                        "id": record.get("id"),
                        "source_file": record.get("source_file"),
                        "heading_path": record.get("heading_path"),
                        "word_count": record.get("word_count"),
                    }
                )

    summary = {
        "status": "ok" if not errors else "error",
        "lines_checked": lines_checked,
        "unique_ids": len(ids),
        "source_file_count": len(source_files),
        "word_count": {
            "min": min(word_counts) if word_counts else 0,
            "max": max(word_counts) if word_counts else 0,
            "mean": round(statistics.mean(word_counts), 2) if word_counts else 0,
            "median": round(statistics.median(word_counts), 2) if word_counts else 0,
        },
        "examples": examples,
        "errors": errors[:50],
        "error_count": len(errors),
    }
    print(json.dumps(summary, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
