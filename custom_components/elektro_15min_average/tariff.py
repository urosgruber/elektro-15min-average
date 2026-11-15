"""Slovenian network tariff time blocks (časovni bloki).

The block depends on the season, on the type of day and on the hour.
Block 1 is the most expensive. The tables give the block of each hour of the
day, one digit per hour from 00:00.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

# Valid up to the end of 2026.
SCHEDULE_UNTIL_2026 = {
    (True, False): "333333211111112211112233",
    (True, True): "444444322222223322223344",
    (False, False): "444444322222223322223344",
    (False, True): "555555433333334433334455",
}

# From 1 January 2027. Source: Agencija za energijo, act of 29 September
# 2025, Annex 2, chapter 3.
SCHEDULE_FROM_2027_START = date(2027, 1, 1)
SCHEDULE_FROM_2027 = {
    (True, False): "333333111111222221112233",
    (True, True): "444444333333444443333344",
    (False, False): "555555333333444443333355",
    (False, True): "555555444444555554444455",
}

# Fixed public holidays that are not working days (month, day).
_FIXED_HOLIDAYS = {
    (1, 1),
    (1, 2),
    (2, 8),
    (4, 27),
    (5, 1),
    (5, 2),
    (6, 25),
    (8, 15),
    (10, 31),
    (11, 1),
    (12, 25),
    (12, 26),
}

BLOCKS = (1, 2, 3, 4, 5)

# The cheap blocks, and how far the forward walk looks.
CHEAP_BLOCKS = (3, 4, 5)
_STEP = timedelta(minutes=15)
_HORIZON = timedelta(hours=48)


def easter_sunday(year: int) -> date:
    """Return Easter Sunday (Gregorian calendar, Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    j = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * j) // 451
    month, day = divmod(h + j - 7 * m + 114, 31)
    return date(year, month, day + 1)


def is_high_season(day: date) -> bool:
    """Return True from November to February."""
    return day.month in (11, 12, 1, 2)


def is_working_day(day: date) -> bool:
    """Return False on Saturday, Sunday and public holidays (built-in list).

    The list is the fallback. A holiday calendar or a workday sensor from
    Home Assistant can replace it (option day_entity).

    Easter Sunday and Whit Sunday are Sundays, so only Easter Monday needs
    its own check.
    """
    if day.weekday() >= 5 or (day.month, day.day) in _FIXED_HOLIDAYS:
        return False
    return day != easter_sunday(day.year) + timedelta(days=1)


def block_at(local: datetime, working_day: bool | None = None) -> int:
    """Return the tariff block at a local date and time.

    working_day overrides the built-in holiday list, for example with the
    state of a holiday calendar or a workday sensor.
    """
    day = local.date()
    if working_day is None:
        working_day = is_working_day(day)
    schedule = (
        SCHEDULE_FROM_2027 if day >= SCHEDULE_FROM_2027_START else SCHEDULE_UNTIL_2026
    )
    hours = schedule[(is_high_season(day), not working_day)]
    return int(hours[local.hour])


def _walk(
    local: datetime, working_day: Callable[[date], bool] | None
) -> tuple[int, list[tuple[datetime, int]]]:
    """Return the block now and every block start in the next 48 hours.

    The walk goes in 15-minute steps from the quarter hour of local. A day
    that working_day does not know uses the built-in holiday list. With an
    aware local, the steps are real time (UTC), so 48 hours stay 48 hours
    over a DST change. The results are in the zone of local.
    """
    zone = local.tzinfo

    def to_local(moment: datetime) -> datetime:
        return moment.astimezone(zone) if zone else moment

    def block(moment: datetime) -> int:
        day_type = working_day(moment.date()) if working_day else None
        return block_at(moment, day_type)

    start = local.replace(minute=local.minute // 15 * 15, second=0, microsecond=0)
    clock = start.astimezone(UTC) if zone else start
    current = block(start)
    previous = current
    starts: list[tuple[datetime, int]] = []
    moment = clock
    while moment - clock < _HORIZON:
        moment += _STEP
        local_moment = to_local(moment)
        value = block(local_moment)
        if value != previous:
            starts.append((local_moment, value))
            previous = value
    return current, starts


def next_change(
    local: datetime, working_day: Callable[[date], bool] | None = None
) -> tuple[datetime, int] | None:
    """Return the start and the block of the next block change.

    local is a local date and time. working_day tells whether a date is a
    working day, like the working-day source of the sensor. The result is
    None when the block does not change within 48 hours.
    """
    _, starts = _walk(local, working_day)
    return starts[0] if starts else None


def next_cheap_start(
    local: datetime, working_day: Callable[[date], bool] | None = None
) -> datetime | None:
    """Return the start of the next block 3, 4 or 5 period.

    The result is None when the block is already 3, 4 or 5, and when no cheap
    period starts within 48 hours.
    """
    current, starts = _walk(local, working_day)
    if current in CHEAP_BLOCKS:
        return None
    return next((moment for moment, value in starts if value in CHEAP_BLOCKS), None)


def parse_block(text: str | None) -> int | None:
    """Read a block from an entity state such as "2", "b2" or "Blok 2"."""
    if not text:
        return None
    digits = [ch for ch in text if ch.isdigit()]
    if len(digits) != 1:
        return None
    block = int(digits[0])
    return block if block in BLOCKS else None
