"""House-rule enforcement and sleep-state derivation (no SDK/robot needed)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from soulmount_body.house import HouseRules
from soulmount_body.state import sleep_info

UTC = ZoneInfo("UTC")


def test_quiet_hours_overnight_wrap():
    h = HouseRules.from_dict({"quiet_start": "21:30", "quiet_end": "07:30"})
    assert h.in_quiet_hours(datetime(2026, 7, 23, 22, 0, tzinfo=UTC))   # late evening
    assert h.in_quiet_hours(datetime(2026, 7, 23, 3, 0, tzinfo=UTC))    # small hours
    assert not h.in_quiet_hours(datetime(2026, 7, 23, 12, 0, tzinfo=UTC))  # noon


def test_volume_clamped_to_ceiling():
    h = HouseRules(volume_ceiling=60)
    assert h.clamp_volume(100) == 60
    assert h.clamp_volume(40) == 40
    assert h.clamp_volume(-5) == 0


def test_camera_capture_on_request_only():
    h = HouseRules(camera_capture="on-request-only")
    assert h.camera_capture_allowed(on_explicit_request=True) is True
    assert h.camera_capture_allowed(on_explicit_request=False) is False


def test_house_from_brain_dict_defaults():
    h = HouseRules.from_dict(None)
    assert h.volume_ceiling == 60 and h.camera_capture == "on-request-only"


def test_sleep_info():
    assert sleep_info(None) == (False, None)
    awake = {"budget": {"state": "awake"}}
    assert sleep_info(awake) == (False, None)
    asleep = {"budget": {"state": "asleep", "wake_at": "2026-07-24T00:00:00+00:00"}}
    assert sleep_info(asleep) == (True, "2026-07-24T00:00:00+00:00")
