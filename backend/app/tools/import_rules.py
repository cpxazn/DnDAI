from __future__ import annotations

import argparse

from backend.app.core.config import get_settings
from backend.app.db.session import initialize_database, get_connection
from backend.app.services.rules_service import import_rules_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import processed rules JSONL into SQLite.")
    parser.add_argument("--jsonl-path", default=None)
    parser.add_argument("--source-name", default="dnd-5e-srd-markdown")
    parser.add_argument("--source-version", default="SRD 5.2.1")
    parser.add_argument("--ruleset", default="SRD 5.2.1")
    parser.add_argument("--chunker-version", default="rules_chunk_markdown_v1")
    parser.add_argument("--source-commit-hash", default=None)
    parser.add_argument("--notes", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    jsonl_path = args.jsonl_path or str(settings.rules_jsonl_file)
    initialize_database(settings.database_file)
    with get_connection(settings.database_file) as connection:
        import_id = import_rules_jsonl(
            connection,
            jsonl_path=jsonl_path,
            source_name=args.source_name,
            source_version=args.source_version,
            ruleset=args.ruleset,
            chunker_version=args.chunker_version,
            source_commit_hash=args.source_commit_hash,
            notes=args.notes,
        )
    print(
        f"Imported rules into {settings.database_file} from {jsonl_path} "
        f"(import_id={import_id})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
