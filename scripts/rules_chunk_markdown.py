#!/usr/bin/env python3
"""
Chunk markdown SRD sources into JSONL records suitable for SQLite import and retrieval.

Example:
    python scripts/rules_chunk_markdown.py ^
      --input-dir dnd-5e-srd-markdown ^
      --output data/rules/processed/srd_5_2_1_chunks.jsonl ^
      --ruleset "SRD 5.2.1"
"""

from __future__ import annotations

import argparse
import html
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


EXCLUDED_FILES = {
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
}

TAG_KEYWORDS = {
    "combat": ["attack", "damage", "combat", "initiative", "reaction", "armor class"],
    "magic": ["spell", "spellcasting", "cantrip", "ritual", "slot", "arcane"],
    "movement": ["move", "movement", "speed", "climb", "swim", "jump", "crawl"],
    "rest": ["short rest", "long rest", "rest"],
    "conditions": ["condition", "grappled", "invisible", "poisoned", "stunned"],
    "skills": ["ability check", "skill", "stealth", "perception", "investigation"],
    "equipment": ["weapon", "armor", "gear", "equipment", "shield"],
    "class": ["class", "barbarian", "wizard", "cleric", "fighter", "rogue"],
    "monster": ["monster", "creature", "hit points", "challenge rating", "large beast", "medium humanoid"],
}

MOJIBAKE_REPLACEMENTS = {
    "â€™": "'",
    "â€œ": '"',
    "â€": '"',
    "â€“": "-",
    "â€”": "-",
    "â€¦": "...",
    "âˆ’": "-",
    "Â ": " ",
    "Â": "",
}

UNICODE_PUNCT_TRANSLATIONS = str.maketrans(
    {
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "−": "-",
        "…": "...",
        "\u00a0": " ",
    }
)


@dataclass
class Section:
    source_file: str
    level: int
    heading_path: list[str]
    text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path, help="Path to markdown SRD directory.")
    parser.add_argument("--output", required=True, type=Path, help="Path to output JSONL.")
    parser.add_argument("--ruleset", default="SRD 5.2.1")
    parser.add_argument("--min-words", type=int, default=1)
    parser.add_argument("--max-words", type=int, default=700)
    parser.add_argument("--overlap-paragraphs", type=int, default=1)
    return parser.parse_args()


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", value) or "section"


def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def fix_mojibake(text: str) -> str:
    repaired = text
    for bad, good in MOJIBAKE_REPLACEMENTS.items():
        repaired = repaired.replace(bad, good)
    return repaired.translate(UNICODE_PUNCT_TRANSLATIONS)


def strip_markdown_inline(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text


def clean_line(line: str) -> str:
    line = html.unescape(fix_mojibake(line))
    line = re.sub(r"<br\s*/?>", "\n", line, flags=re.IGNORECASE)
    line = re.sub(r"</?(hr|table|thead|tbody|ul|ol|p|div)>", "\n", line, flags=re.IGNORECASE)
    line = re.sub(r"</tr>", "\n", line, flags=re.IGNORECASE)
    line = re.sub(r"</t[dh]>", " | ", line, flags=re.IGNORECASE)
    line = re.sub(r"<[^>]+>", "", line)
    line = strip_markdown_inline(line)
    line = re.sub(r"^\s*>\s?", "", line)
    line = re.sub(r"[ \t]+", " ", line)
    return line.strip()


def clean_text(text: str) -> str:
    text = html.unescape(fix_mojibake(text))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]+\n", "\n\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def markdown_files(input_dir: Path) -> list[Path]:
    files = []
    for path in sorted(input_dir.glob("*.md")):
        if path.name in EXCLUDED_FILES:
            continue
        files.append(path)
    return files


def parse_sections(path: Path) -> list[Section]:
    raw_text = path.read_text(encoding="utf-8").lstrip("\ufeff")
    lines = raw_text.splitlines()
    sections: list[Section] = []
    heading_stack: list[tuple[int, str]] = []
    current_level = 0
    current_path: list[str] = []
    current_lines: list[str] = []

    def flush_current() -> None:
        nonlocal current_lines
        if not current_path:
            current_lines = []
            return
        cleaned_lines: list[str] = []
        pending_table_bits: list[str] = []
        for raw_line in current_lines:
            line = clean_line(raw_line)
            if not line:
                if pending_table_bits:
                    cleaned_lines.append(" ".join(pending_table_bits).strip(" |"))
                    pending_table_bits = []
                if cleaned_lines and cleaned_lines[-1] != "":
                    cleaned_lines.append("")
                continue

            if "|" in line and raw_line.lstrip().startswith("<"):
                pending_table_bits.append(line.strip(" |"))
                if raw_line.strip().lower().startswith("</tr"):
                    cleaned_lines.append(" | ".join(bit for bit in pending_table_bits if bit))
                    pending_table_bits = []
                continue

            if pending_table_bits:
                cleaned_lines.append(" | ".join(bit for bit in pending_table_bits if bit))
                pending_table_bits = []
            cleaned_lines.append(line)

        if pending_table_bits:
            cleaned_lines.append(" | ".join(bit for bit in pending_table_bits if bit))

        text = clean_text("\n".join(cleaned_lines))
        if text:
            sections.append(
                Section(
                    source_file=path.name,
                    level=current_level,
                    heading_path=current_path.copy(),
                    text=text,
                )
            )
        current_lines = []

    for raw_line in lines:
        heading_match = re.match(r"^\s*(#{1,6})\s+(.*?)\s*$", raw_line)
        if heading_match:
            flush_current()
            level = len(heading_match.group(1))
            title = clean_line(heading_match.group(2))
            heading_stack = [entry for entry in heading_stack if entry[0] < level]
            heading_stack.append((level, title))
            current_level = level
            current_path = [title for _, title in heading_stack]
            continue
        current_lines.append(raw_line)

    flush_current()
    return sections


def split_large_section(text: str, max_words: int, overlap_paragraphs: int) -> list[str]:
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for paragraph in paragraphs:
        para_words = count_words(paragraph)
        if current and current_words + para_words > max_words:
            chunks.append("\n\n".join(current).strip())
            overlap = current[-overlap_paragraphs:] if overlap_paragraphs > 0 else []
            current = overlap.copy()
            current_words = count_words("\n\n".join(current))
        current.append(paragraph)
        current_words += para_words

    if current:
        chunks.append("\n\n".join(current).strip())

    return chunks


def derive_tags(source_file: str, heading_path: list[str], text: str) -> list[str]:
    haystack = "\n".join([source_file, *heading_path, text]).lower()
    tags = [tag for tag, needles in TAG_KEYWORDS.items() if any(needle in haystack for needle in needles)]
    return sorted(tags)


def build_record(
    ruleset: str,
    section: Section,
    text: str,
    part_index: int,
    chunk_count: int,
) -> dict:
    path_without_root = section.heading_path[1:] if len(section.heading_path) > 1 else section.heading_path
    chapter = section.heading_path[0] if section.heading_path else None
    section_name = path_without_root[0] if path_without_root else chapter
    subsection = path_without_root[1] if len(path_without_root) > 1 else None
    part = path_without_root[2] if len(path_without_root) > 2 else None

    id_parts = [slugify(section.source_file.replace(".md", ""))]
    id_parts.extend(slugify(piece) for piece in section.heading_path)
    record_id = "-".join(part for part in id_parts if part)
    if chunk_count > 1:
        record_id = f"{record_id}-part-{part_index}"

    return {
        "id": record_id,
        "doc_type": "rules_reference",
        "ruleset": ruleset,
        "source_file": section.source_file,
        "chapter": chapter,
        "section": section_name,
        "subsection": subsection,
        "part": part,
        "heading_path": section.heading_path,
        "word_count": count_words(text),
        "tags": derive_tags(section.source_file, section.heading_path, text),
        "text": text,
    }


def build_records(
    ruleset: str,
    sections: list[Section],
    min_words: int,
    max_words: int,
    overlap_paragraphs: int,
) -> list[dict]:
    records: list[dict] = []
    for section in sections:
        if count_words(section.text) < min_words:
            continue
        chunks = split_large_section(section.text, max_words=max_words, overlap_paragraphs=overlap_paragraphs)
        if not chunks:
            continue
        for index, chunk_text in enumerate(chunks, start=1):
            records.append(build_record(ruleset, section, chunk_text, index, len(chunks)))
    return records


def write_jsonl(records: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    args = parse_args()
    files = markdown_files(args.input_dir)
    all_sections: list[Section] = []
    for path in files:
        all_sections.extend(parse_sections(path))

    records = build_records(
        ruleset=args.ruleset,
        sections=all_sections,
        min_words=args.min_words,
        max_words=args.max_words,
        overlap_paragraphs=args.overlap_paragraphs,
    )
    write_jsonl(records, args.output)

    print(
        json.dumps(
            {
                "status": "ok",
                "input_dir": str(args.input_dir),
                "output": str(args.output),
                "file_count": len(files),
                "section_count": len(all_sections),
                "chunk_count": len(records),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
