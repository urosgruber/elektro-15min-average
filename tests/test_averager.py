"""Tests of the interval arithmetic, without Home Assistant running."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.elektro_15min_average.averager import (
    FinishedInterval,
    IntervalAverager,
)

T0 = datetime(2026, 11, 15, 16, 0, tzinfo=UTC)


def m(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_time_weighted_average_equals_energy_over_time() -> None:
    a = IntervalAverager()
    a.add_sample(500, m(0))
    a.add_sample(2500, m(5))
    assert a.average(m(10)) == pytest.approx(1500)
    finished = a.finalize_until(m(15))
    assert finished is not None
    assert finished.average == pytest.approx((500 * 5 + 2500 * 10) / 15)
    assert finished.arithmetic == pytest.approx(1500)
    assert finished.coverage == pytest.approx(1.0)


def test_many_samples_do_not_get_more_weight() -> None:
    """The flaw of the arithmetic mean: a burst of samples skews it."""
    a = IntervalAverager()
    a.add_sample(400, m(0))
    for i in range(20):  # 20 samples in the last minute
        a.add_sample(3000, m(14 + i / 20))
    finished = a.finalize_until(m(15))
    assert finished.average == pytest.approx((400 * 14 + 3000 * 1) / 15)
    assert finished.arithmetic > 2800


def test_projected_holds_the_latest_power() -> None:
    a = IntervalAverager()
    a.add_sample(1000, m(0))
    a.add_sample(3000, m(5))
    assert a.projected(m(5)) == pytest.approx((1000 * 5 + 3000 * 10) / 15)
    assert a.projected(m(10)) == pytest.approx((1000 * 5 + 3000 * 10) / 15)
    a.add_sample(0, m(10))
    assert a.projected(m(10)) == pytest.approx((1000 * 5 + 3000 * 5) / 15)


def test_projected_equals_average_at_the_end() -> None:
    a = IntervalAverager()
    a.add_sample(1200, m(0))
    a.add_sample(300, m(7))
    assert a.projected(m(15)) == pytest.approx(a.average(m(15)))


def test_value_carries_into_the_next_interval() -> None:
    a = IntervalAverager()
    a.add_sample(2500, m(0))
    a.finalize_until(m(15))
    # At the boundary the carried power shows, not unknown.
    assert a.average(m(15)) == 2500
    a.add_sample(1000, m(20))
    assert a.average(m(25)) == pytest.approx((2500 * 5 + 1000 * 5) / 10)


def test_restore_drops_an_ended_interval() -> None:
    a = IntervalAverager()
    a.add_sample(800, m(0))
    data = a.to_dict()
    b = IntervalAverager()
    assert b.restore(data, m(16)) is False
    assert b.interval_start is None


def test_restore_does_not_count_the_downtime() -> None:
    a = IntervalAverager()
    a.add_sample(2500, m(0))
    a.add_sample(1000, m(5))
    data = a.to_dict()  # saved at minute 5
    b = IntervalAverager()
    assert b.restore(data, m(8)) is True
    assert b.restart_detected
    b.add_sample(200, m(10))  # minutes 5 to 10 are unknown
    finished = b.finalize_until(m(15))
    assert finished.average == pytest.approx((2500 * 5 + 200 * 5) / 10)
    assert finished.coverage == pytest.approx(10 / 15)
    assert finished.restart_detected


def test_long_gap_starts_a_fresh_interval() -> None:
    a = IntervalAverager()
    a.add_sample(900, m(0))
    finished = a.finalize_until(m(50))
    assert finished.start == m(0)
    assert a.interval_start == m(45)
    # The power during the gap is unknown, so nothing is held.
    assert a.last_sample_ts is None


def test_finished_interval_round_trip() -> None:
    a = IntervalAverager()
    a.add_sample(700, m(0))
    finished = a.finalize_until(m(15))
    assert FinishedInterval.from_dict(finished.to_dict()) == finished
    assert FinishedInterval.from_dict({}) is None
