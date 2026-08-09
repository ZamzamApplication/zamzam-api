"""Build api/app/quran_lines_data.py from the offline QCF4 mushaf dataset.

The source is the open quran-qcf4 repository
(https://github.com/MohamadHajjRabee/quran-qcf4), which renders the Madani
15-line mushaf (QCF4, Madinah Mushaf 1441H, calligraphy Uthman Taha, King
Fahd Complex). Each page JSON carries one entry per printed line; lines that
only hold a surah title or the basmala are layout decorations and are
excluded from recitation lines.

The generated module is committed so migrations can seed the ``quran_lines``
reference table without network access.

Usage:
    python scripts/build_quran_lines.py /path/to/quran-qcf4/pages
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Standard Madani ayah counts, matching web/src/lib/quran.ts.
AYAH_COUNTS = [
    7, 286, 200, 176, 120, 165, 206, 75, 129, 109, 123, 111, 43, 52, 99, 128,
    111, 110, 98, 135, 112, 78, 118, 64, 77, 227, 93, 88, 69, 60, 34, 30, 73,
    54, 45, 83, 182, 88, 75, 85, 54, 53, 89, 59, 37, 35, 38, 29, 18, 45, 60,
    49, 62, 55, 78, 96, 29, 22, 24, 13, 14, 11, 11, 18, 12, 12, 30, 52, 52, 44,
    28, 28, 20, 56, 40, 31, 50, 40, 46, 42, 29, 19, 36, 25, 22, 17, 19, 26, 30,
    20, 15, 21, 11, 8, 8, 19, 5, 8, 8, 11, 11, 8, 3, 9, 5, 4, 7, 3, 6, 3, 5, 4,
    5, 6,
]

# Commit of the quran-qcf4 repository this data was built from.
SOURCE_COMMIT = "ccf9fefea56a957d1e3b161f17ad72b3bd2cb1ae"


def build_offsets() -> list[tuple[int, int]]:
    """Return cumulative (surah, ayah) offsets, one entry per ayah (1-indexed)."""
    ayahs: list[tuple[int, int]] = []
    for surah, count in enumerate(AYAH_COUNTS, start=1):
        for ayah in range(1, count + 1):
            ayahs.append((surah, ayah))
    return ayahs


def parse_verse_key(key: str) -> tuple[int, int]:
    surah, _, ayah = key.partition(":")
    return (int(surah), int(ayah))


def extract_lines(pages_dir: Path) -> list[dict]:
    lines: list[dict] = []
    for page_number in range(1, 605):
        with open(pages_dir / f"{page_number:03d}.json", encoding="utf-8") as f:
            page = json.load(f)
        if page["page"] != page_number:
            raise SystemExit(f"page number mismatch at {page_number:03d}.json")
        for entry in page["lines"]:
            words = [w for w in entry["words"] if w.get("verse_key")]
            if not words:
                continue
            lines.append({
                "page": page_number,
                "line": entry["line"],
                "start": parse_verse_key(words[0]["verse_key"]),
                "end": parse_verse_key(words[-1]["verse_key"]),
            })
    return lines


def validate(lines: list[dict], ayahs: list[tuple[int, int]]) -> None:
    offsets = {ayah: index for index, ayah in enumerate(ayahs, start=1)}
    total = len(ayahs)

    if len(lines) < 6000:
        raise SystemExit(f"suspiciously few lines: {len(lines)}")

    covered: set[int] = set()
    previous_end: int | None = None
    previous_key = None
    for line in lines:
        if line["start"] > line["end"]:
            raise SystemExit(f"start after end: {line}")
        start_off = offsets.get(line["start"])
        end_off = offsets.get(line["end"])
        if start_off is None or end_off is None:
            raise SystemExit(f"out of range verse key: {line}")
        if previous_end is not None and start_off > previous_end + 1:
            raise SystemExit(
                f"gap between lines after {previous_key}: {line}"
            )
        if start_off < previous_end if previous_end is not None else False:
            raise SystemExit(f"line out of order: {line}")
        covered.update(range(start_off, end_off + 1))
        previous_end = end_off
        previous_key = line["end"]

    if len(covered) != total:
        missing = [ayahs[i - 1] for i in range(1, total + 1) if i not in covered]
        raise SystemExit(f"coverage {len(covered)}/{total}, missing: {missing[:10]}")

    if lines[0]["start"] != (1, 1):
        raise SystemExit(f"mushaf must start at 1:1, got {lines[0]['start']}")
    if lines[-1]["end"] != (114, 6):
        raise SystemExit(f"mushaf must end at 114:6, got {lines[-1]['end']}")

    pages = {line["page"] for line in lines}
    if len(pages) != 604:
        raise SystemExit(f"expected 604 pages, got {len(pages)}")

    print(f"validated {len(lines)} recitation lines across {len(pages)} pages")


def emit_module(lines: list[dict], ayahs: list[tuple[int, int]], target: Path) -> None:
    offsets = {ayah: index for index, ayah in enumerate(ayahs, start=1)}
    rows = [
        (line["page"], line["line"], *line["start"], *line["end"])
        for line in lines
    ]
    min_off = min(offsets[line["start"]] for line in lines)
    max_off = max(offsets[line["end"]] for line in lines)

    header = f'''"""Generated reference table: Madani 15-line mushaf line -> ayah ranges.

DO NOT EDIT BY HAND.

Source: quran-qcf4 (QCF4, Madinah Mushaf 1441H) at commit {SOURCE_COMMIT}.
Each tuple is (page, line, start_surah, start_ayah, end_surah, end_ayah)
for one recitation line. Surah titles and basmala layout lines are excluded,
so pages can have fewer than 15 recitation lines (page 1 and 2 are special).

Totals: {len(rows)} lines, ayah offset span {min_off}..{max_off}
of {len(ayahs)} ayahs.
"""

QURAN_LINES: tuple[tuple[int, int, int, int, int, int], ...] = (
'''
    body = "".join(f"    {row!r},\n" for row in rows)
    footer = ")\n"
    target.write_text(header + body + footer, encoding="utf-8")
    print(f"wrote {target} ({len(rows)} rows, {target.stat().st_size} bytes)")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_quran_lines.py /path/to/quran-qcf4/pages")
    pages_dir = Path(sys.argv[1])
    if not pages_dir.is_dir():
        raise SystemExit(f"not a directory: {pages_dir}")
    ayahs = build_offsets()
    lines = extract_lines(pages_dir)
    validate(lines, ayahs)
    target = Path(__file__).resolve().parent.parent / "app" / "quran_lines_data.py"
    emit_module(lines, ayahs, target)


if __name__ == "__main__":
    main()
