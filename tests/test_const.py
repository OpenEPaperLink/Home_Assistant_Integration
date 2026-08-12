"""Confirm the package imports and the test harness is wired up."""

from __future__ import annotations

from custom_components.open_epaper_link.const import DOMAIN, REMOVED_SENSOR_KEYS


def test_domain_is_unchanged() -> None:
    """The domain must not change: existing config entries reference it."""
    assert DOMAIN == "open_epaper_link"


def test_removed_sensor_keys() -> None:
    """These four derived sensors are dropped; migration cleans them up."""
    assert REMOVED_SENSOR_KEYS == {
        "runtime",
        "boot_count",
        "checkin_count",
        "block_requests",
    }
