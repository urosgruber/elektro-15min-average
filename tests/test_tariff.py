"""Tests of the tariff block calculation."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.elektro_15min_average.tariff import (
    block_at,
    easter_sunday,
    is_working_day,
    next_change,
    next_cheap_start,
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


def at(moment: str) -> datetime:
    return datetime.fromisoformat(moment)


@pytest.mark.parametrize(
    ("now", "change", "block", "cheap"),
    [
        # 2026 table, winter working day: 7-14 b1, 14-16 b2, 16-20 b1, 20-22 b2.
        ("2026-11-16 10:00", "2026-11-16 14:00", 2, "2026-11-16 22:00"),
        # Block 2 at 21:00: block 3 starts at 22:00.
        ("2026-11-16 21:00", "2026-11-16 22:00", 3, "2026-11-16 22:00"),
        # Friday 21:00. Saturday is block 4 all night, but 22:00 comes first.
        ("2026-11-20 21:00", "2026-11-20 22:00", 3, "2026-11-20 22:00"),
        # 31 December 2026 still uses the 2026 table.
        ("2026-12-31 21:00", "2026-12-31 22:00", 3, "2026-12-31 22:00"),
        # From 2027: 06-12 b1, 12-17 b2, 17-20 b1, 20-22 b2.
        ("2027-01-04 06:30", "2027-01-04 12:00", 2, "2027-01-04 22:00"),
        # Late evening before the table switch: the change is after midnight.
        ("2026-12-31 23:30", "2027-01-01 00:00", 4, None),
    ],
)
def test_next_change_and_cheap_start(
    now: str, change: str, block: int, cheap: str | None
) -> None:
    assert next_change(at(now)) == (at(change), block)
    expected = None if cheap is None else at(cheap)
    assert next_cheap_start(at(now)) == expected


def test_next_cheap_start_across_table_switch() -> None:
    assert next_cheap_start(at("2027-01-04 18:00")) == at("2027-01-04 22:00")


def test_next_change_on_a_sunday() -> None:
    # 2026 Sunday in high season, 00:00: block 4 until 06:00 (change to 3).
    assert next_change(at("2026-11-15 00:00")) == (at("2026-11-15 06:00"), 3)


def test_working_day_override_moves_the_change() -> None:
    thursday = at("2026-11-19 16:00")
    assert next_change(thursday) == (at("2026-11-19 20:00"), 2)
    holiday = next_change(thursday, working_day=lambda day: False)
    assert holiday == (at("2026-11-19 20:00"), 3)
    cheap = next_cheap_start(thursday, working_day=lambda day: False)
    assert cheap == at("2026-11-19 20:00")


def test_next_cheap_start_ignores_a_cheap_block_now() -> None:
    assert next_cheap_start(at("2026-11-16 23:00")) is None
    assert next_cheap_start(at("2026-11-16 22:00")) is None


def test_next_change_rounds_down_to_the_quarter() -> None:
    assert next_change(at("2026-11-16 13:59:30")) == (at("2026-11-16 14:00"), 2)


LJUBLJANA = ZoneInfo("Europe/Ljubljana")


def test_next_change_over_the_spring_dst_change() -> None:
    # Sunday 29 March 2026: the clock jumps from 02:00 to 03:00.
    now = datetime(2026, 3, 28, 23, 30, tzinfo=LJUBLJANA)
    assert next_change(now) == (datetime(2026, 3, 29, 6, tzinfo=LJUBLJANA), 4)
    change = next_change(now)
    assert change is not None
    assert change[0].isoformat() == "2026-03-29T06:00:00+02:00"


def test_next_change_over_the_autumn_dst_change() -> None:
    # Sunday 25 October 2026: the clock goes back from 03:00 to 02:00.
    now = datetime(2026, 10, 24, 23, 30, tzinfo=LJUBLJANA)
    change = next_change(now)
    assert change is not None
    assert change[0].isoformat() == "2026-10-25T06:00:00+01:00"
    assert change[1] == 4
