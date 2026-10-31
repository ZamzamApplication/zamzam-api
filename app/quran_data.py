"""Offline Qur'an helpers for persistent student ward plans.

The physical-line reference is generated from the QCF4 Madani 15-line
mushaf and committed with the application, so assignment generation never
depends on a network service.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from math import ceil

from app.quran_lines_data import QURAN_LINES
from app.quran_quarters_data import QURAN_QUARTER_STARTS


SURAH_AYAH_COUNTS = [
    7, 286, 200, 176, 120, 165, 206, 75, 129, 109, 123, 111, 43, 52, 99, 128,
    111, 110, 98, 135, 112, 78, 118, 64, 77, 227, 93, 88, 69, 60, 34, 30, 73,
    54, 45, 83, 182, 88, 75, 85, 54, 53, 89, 59, 37, 35, 38, 29, 18, 45, 60,
    49, 62, 55, 78, 96, 29, 22, 24, 13, 14, 11, 11, 18, 12, 12, 30, 52, 52, 44,
    28, 28, 20, 56, 40, 31, 50, 40, 46, 42, 29, 19, 36, 25, 22, 17, 19, 26, 30,
    20, 15, 21, 11, 8, 8, 19, 5, 8, 8, 11, 11, 8, 3, 9, 5, 4, 7, 3, 6, 3, 5, 4,
    5, 6,
]
TOTAL_AYAHS = sum(SURAH_AYAH_COUNTS)
TOTAL_PAGES = 604

_AYAH_ONE_OFFSETS: list[int] = []
_running_offset = 1
for _count in SURAH_AYAH_COUNTS:
    _AYAH_ONE_OFFSETS.append(_running_offset)
    _running_offset += _count


def global_offset(surah: int, ayah: int) -> int:
    if surah < 1 or surah > 114:
        raise ValueError(f"invalid surah: {surah}")
    count = SURAH_AYAH_COUNTS[surah - 1]
    if ayah < 1 or ayah > count:
        raise ValueError(f"invalid ayah {surah}:{ayah}")
    return _AYAH_ONE_OFFSETS[surah - 1] + ayah - 1


def ayah_at_offset(offset: int) -> tuple[int, int]:
    if offset < 1 or offset > TOTAL_AYAHS:
        raise ValueError(f"offset out of range: {offset}")
    surah = bisect_right(_AYAH_ONE_OFFSETS, offset)
    return (surah, offset - _AYAH_ONE_OFFSETS[surah - 1] + 1)


_LINE_START_OFFSETS = [global_offset(row[2], row[3]) for row in QURAN_LINES]
_LINE_END_OFFSETS = [global_offset(row[4], row[5]) for row in QURAN_LINES]


def _line_index_for_ayah(surah: int, ayah: int) -> int:
    return bisect_left(_LINE_END_OFFSETS, global_offset(surah, ayah))


def lines_to_end(start_surah: int, start_ayah: int, amount: int) -> tuple[int, int]:
    """Return the final ayah touched by ``amount`` physical Mushaf lines."""
    if amount < 1:
        raise ValueError("amount must be positive")
    first = _line_index_for_ayah(start_surah, start_ayah)
    last = min(first + amount - 1, len(QURAN_LINES) - 1)
    return QURAN_LINES[last][4], QURAN_LINES[last][5]


def ayahs_to_end(start_surah: int, start_ayah: int, amount: int) -> tuple[int, int]:
    if amount < 1:
        raise ValueError("amount must be positive")
    start = global_offset(start_surah, start_ayah)
    return ayah_at_offset(min(start + amount - 1, TOTAL_AYAHS))


def next_ayah(surah: int, ayah: int) -> tuple[int, int]:
    return ayah_at_offset(min(global_offset(surah, ayah) + 1, TOTAL_AYAHS))


def pages_to_end(start_page: int, amount: int) -> int:
    if start_page < 1 or start_page > TOTAL_PAGES:
        raise ValueError(f"invalid page: {start_page}")
    if amount < 1:
        raise ValueError("amount must be positive")
    return min(start_page + amount - 1, TOTAL_PAGES)


def next_reverse_ayah(surah: int, ayah: int) -> tuple[int, int] | None:
    """Descend through surahs, preserving ascending ayahs within each surah."""
    global_offset(surah, ayah)
    if ayah < SURAH_AYAH_COUNTS[surah - 1]:
        return surah, ayah + 1
    return (surah - 1, 1) if surah > 1 else None


_QUARTER_OFFSETS = [global_offset(surah, ayah) for surah, ayah in QURAN_QUARTER_STARTS]


def reverse_to_end(surah: int, ayah: int, amount: int, unit: str) -> tuple[int, int]:
    """Allocate the same surah-by-surah reverse traversal as the hifz builder.

    Each segment reads forward, capped at that surah's end. Any remaining
    amount continues at ayah 1 of the preceding surah.
    """
    if amount < 1:
        raise ValueError("amount must be positive")
    global_offset(surah, ayah)
    remaining = amount
    while remaining > 0:
        start = global_offset(surah, ayah)
        surah_end = global_offset(surah, SURAH_AYAH_COUNTS[surah - 1])
        if unit == "ayahs":
            end = min(start + remaining - 1, surah_end)
            used = end - start + 1
        elif unit in ("lines", "half_page"):
            lines_per_unit = 1 if unit == "lines" else 8
            first = _line_index_for_ayah(surah, ayah)
            last = min(first + remaining * lines_per_unit - 1, len(QURAN_LINES) - 1)
            end = min(_LINE_END_OFFSETS[last], surah_end)
            used = ceil((bisect_left(_LINE_END_OFFSETS, end) - first + 1) / lines_per_unit)
        elif unit in ("quarter", "hizb", "juz"):
            quarters_per_unit = {"quarter": 1, "hizb": 4, "juz": 8}[unit]
            following = bisect_right(_QUARTER_OFFSETS, start)
            boundary = following + remaining * quarters_per_unit - 1
            requested_end = _QUARTER_OFFSETS[boundary] - 1 if boundary < len(_QUARTER_OFFSETS) else TOTAL_AYAHS
            end = min(requested_end, surah_end)
            first_quarter = bisect_right(_QUARTER_OFFSETS, start) - 1
            last_quarter = bisect_right(_QUARTER_OFFSETS, end) - 1
            used = ceil((last_quarter - first_quarter + 1) / quarters_per_unit)
        else:
            raise ValueError(f"invalid reverse unit: {unit}")
        end_surah, end_ayah = ayah_at_offset(end)
        remaining -= used
        if remaining <= 0 or (end_surah == 1 and end_ayah == 7):
            return end_surah, end_ayah
        surah, ayah = next_reverse_ayah(end_surah, end_ayah)
    raise AssertionError("unreachable reverse allocation")
