"""Shared fixtures for the OpenEPaperLink test suite."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.open_epaper_link.const import (
    CONF_AP_MAC,
    CONF_HOST,
    DOMAIN,
)

AP_HOST = "192.0.2.10"
AP_MAC = "aa:bb:cc:dd:ee:ff"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Load custom_components/ in every test.

    Without this the integration is invisible to the test hass instance.
    """
    return


@pytest.fixture
def mock_setup_entry() -> Generator[None]:
    """Stop config flow tests from actually setting the integration up."""
    with patch(
        "custom_components.open_epaper_link.async_setup_entry",
        return_value=True,
    ):
        yield


@pytest.fixture
def ap_config_entry() -> MockConfigEntry:
    """A configured AP entry, keyed on the AP's MAC rather than its address."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"OpenEPaperLink {AP_HOST}",
        unique_id=AP_MAC,
        data={CONF_HOST: AP_HOST, CONF_AP_MAC: AP_MAC},
        version=5,
    )
