"""Tests for upload-schedule tracking and poll timing."""

from __future__ import annotations

import pytest

from custom_components.smart_oil_gauge.schedule import (
    GRACE_S,
    MAX_DELAY_S,
    MIN_DELAY_S,
    TankSchedule,
    next_poll_delay,
)

H = 3600.0
T0 = 1_795_035_543.0  # an upload at 3:58 PM


def test_first_config_is_assumed_in_effect() -> None:
    """A newly seen gauge is assumed to already use the portal interval."""
    sched = TankSchedule()
    sched.update_configured(12, 2)
    assert (sched.configured_h, sched.effective_h, sched.num_tanks) == (12, 12, 2)
    assert not sched.pending
    assert sched.interval() == (12.0, "portal")
    assert sched.next_expected(T0) == T0 + 12 * H


def test_portal_change_waits_for_next_upload() -> None:
    """12h -> 1h on the portal only takes effect after the next upload."""
    sched = TankSchedule()
    sched.update_configured(12, 1)
    sched.record_upload(T0)

    # User switches to 1 hour on the portal, mid-cycle.
    sched.update_configured(1, 1)
    assert sched.pending
    # Still expect the upload 12 hours after the last one, not 1 hour.
    assert sched.next_expected(T0) == T0 + 12 * H

    # That upload arrives; the gauge fetched the new setting with it.
    sched.record_upload(T0 + 12 * H)
    assert not sched.pending
    assert sched.effective_h == 1
    assert sched.next_expected(T0 + 12 * H) == T0 + 13 * H


def test_measured_spacing_overrides_disagreeing_setting() -> None:
    """Two consistent spacings that disagree with the setting win."""
    sched = TankSchedule()
    sched.update_configured(12, 1)
    for i in range(3):
        sched.record_upload(T0 + i * 6 * H + i * 60)
    hours, source = sched.interval()
    assert source == "measured"
    assert hours == pytest.approx(6.0, abs=0.05)


def test_measured_spacing_ignored_when_inconsistent() -> None:
    """Irregular spacings (a missed upload) don't override the setting."""
    sched = TankSchedule()
    sched.update_configured(12, 1)
    for ts in (T0, T0 + 12 * H, T0 + 36 * H):
        sched.record_upload(ts)
    assert sched.measured_h() is None
    assert sched.interval() == (12.0, "portal")


def test_measured_only_and_unknown() -> None:
    """Without a readable setting, measured spacing is used; else unknown."""
    sched = TankSchedule()
    assert sched.interval() == (None, "unknown")
    assert sched.next_expected(T0) is None
    for i in range(3):
        sched.record_upload(T0 + i * 12 * H)
    assert sched.interval() == (12.0, "measured")


def test_record_upload_ignores_repeats_and_keeps_recent() -> None:
    """The same upload is recorded once; only recent uploads are kept."""
    sched = TankSchedule()
    sched.record_upload(T0)
    sched.record_upload(T0)
    assert sched.upload_times == [T0]
    for i in range(1, 10):
        sched.record_upload(T0 + i * H)
    assert len(sched.upload_times) == 6


def test_storage_round_trip_and_garbage() -> None:
    """Schedules survive storage; malformed values are dropped."""
    sched = TankSchedule(configured_h=1, effective_h=12, num_tanks=2)
    sched.upload_times = [T0, T0 + 12 * H]
    again = TankSchedule.from_dict(sched.as_dict())
    assert again.as_dict() == sched.as_dict()
    assert again.pending
    bad = TankSchedule.from_dict(
        {"configured_h": "x", "effective_h": 99, "num_tanks": 2, "upload_times": "no"}
    )
    assert (bad.configured_h, bad.effective_h, bad.upload_times) == (None, None, [])
    assert TankSchedule.from_dict(None).as_dict() == TankSchedule().as_dict()


def test_next_poll_shortly_after_expected_upload() -> None:
    """Poll a few minutes after the earliest expected upload."""
    expected = T0 + 12 * H
    now = expected - H
    delay, at = next_poll_delay(now, [expected, expected + 3 * H], 6 * H)
    assert at == expected + GRACE_S
    assert delay == pytest.approx(H + GRACE_S)


def test_next_poll_retries_when_late() -> None:
    """A late upload is retried at +15, +45, +105 minutes, then hourly."""
    due = T0 + GRACE_S
    assert next_poll_delay(due + 1, [T0], 6 * H)[1] == due + 15 * 60
    assert next_poll_delay(due + 16 * 60, [T0], 6 * H)[1] == due + 45 * 60
    assert next_poll_delay(due + 46 * 60, [T0], 6 * H)[1] == due + 105 * 60
    assert next_poll_delay(due + 106 * 60, [T0], 6 * H)[1] == due + 165 * 60
    assert next_poll_delay(due + 10 * H, [T0], 6 * H)[1] == due + 105 * 60 + 9 * H


def test_next_poll_bounds_and_fallback() -> None:
    """Delays stay within bounds; no expectations means the fallback."""
    assert next_poll_delay(T0, [T0 + 24 * H], 6 * H)[0] == MAX_DELAY_S
    assert next_poll_delay(T0, [T0 - GRACE_S + 5], 6 * H)[0] == MIN_DELAY_S
    assert next_poll_delay(T0, [], 3 * H)[0] == 3 * H
