"""Tests of the tariff block calculation."""

from datetime import date, datetime

import pytest

from custom_components.elektro_15min_average.tariff import (
    block_at,
    easter_sunday,
    is_working_day,
    parse_block,
)


@pytest.mark.parametrize(
    ("year", "expected"),
    [(2024, date(2024, 3, 31)), (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28))],
)
def test_easter(year: int, expected: date) -> None:
    assert easter_sunday(year) == expected


def test_working_days() -> None:
    assert is_working_day(date(2026, 11, 16))  # Monday
    assert not is_working_day(date(2026, 11, 15))  # Sunday
    assert not is_working_day(date(2026, 12, 25))  # Christmas
    assert not is_working_day(date(2026, 4, 6))  # Easter Monday
    assert not is_working_day(date(2027, 3, 29))  # Easter Monday


@pytest.mark.parametrize(
    ("moment", "block"),
    [
        # High season, working day (Monday 16 November 2026).
        ("2026-11-16 03:00", 3),
        ("2026-11-16 06:30", 2),
        ("2026-11-16 08:00", 1),
        ("2026-11-16 14:15", 2),
        ("2026-11-16 18:45", 1),
        ("2026-11-16 21:00", 2),
        ("2026-11-16 23:30", 3),
        # High season, Sunday.
        ("2026-11-15 08:00", 2),
        ("2026-11-15 02:00", 4),
        # Low season, working day and holiday.
        ("2026-05-04 08:00", 2),
        ("2026-04-06 08:00", 3),  # Easter Monday
        ("2026-04-06 02:00", 5),
        # From 2027 (new table), high season working day.
        ("2027-01-04 08:00", 1),
        ("2027-01-04 13:00", 2),
        ("2027-01-04 18:00", 1),
        # From 2027, low season working day.
        ("2027-05-03 08:00", 3),
        ("2027-05-03 13:00", 4),
        ("2027-05-03 02:00", 5),
    ],
)
def test_block_at(moment: str, block: int) -> None:
    assert block_at(datetime.fromisoformat(moment)) == block


def test_working_day_override() -> None:
    monday = datetime.fromisoformat("2026-11-16 08:00")
    assert block_at(monday, working_day=False) == 2
    sunday = datetime.fromisoformat("2026-11-15 08:00")
    assert block_at(sunday, working_day=True) == 1


@pytest.mark.parametrize(
    ("text", "block"),
    [("2", 2), ("b3", 3), ("Blok 5", 5), ("b6", None), ("b1,b2", None), ("", None)],
)
def test_parse_block(text: str, block: int | None) -> None:
    assert parse_block(text) == block
