"""Invariants that must not drift."""

from __future__ import annotations

from custom_components.open_epaper_link.const import DOMAIN


def test_domain_is_unchanged() -> None:
    """Existing config entries reference this; changing it orphans them all."""
    assert DOMAIN == "open_epaper_link"
