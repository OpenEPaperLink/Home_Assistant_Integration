"""Selects for Access Point settings with a fixed set of choices.

Option values are stable machine strings; their display text lives in
strings.json. The pre-4.0 integration used English prose as the option value,
which meant the entity state itself was untranslatable and could not be
reworded without breaking recorder history and automations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import APCoordinator, OpenEPaperLinkConfigEntry
from .entity import OpenEPaperLinkAPEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class APSelectDescription(SelectEntityDescription):
    """Describes an Access Point setting chosen from a fixed set.

    ``key`` doubles as the wire key the Access Point expects. ``choices`` maps
    each option value to the integer the Access Point stores.
    """

    attribute: str
    choices: dict[str, int]
    requires: str | None = None
    options: list[str] = field(default_factory=list)


def _numbered(prefix: str, values: dict[str, int]) -> dict[str, int]:
    """Build a choice map, keeping keys valid as translation identifiers."""
    return {f"{prefix}{name}": value for name, value in values.items()}


_BRIGHTNESS = {"off": 0, "low": 63, "medium": 127, "high": 191, "max": 255}
_CHANNELS = {f"ch{n}": n for n in (11, 15, 20, 25, 26)}
_SUBGHZ = {"off": 0, "ch103": 103, "ch104": 104, "ch105": 105}
_MAX_SLEEP = {"h1": 1, "h4": 4, "h12": 12, "h24": 24, "h48": 48}
_LOCK = {"open": 0, "learning": 1, "locked": 2}
_WIFI_POWER = {"low": 1, "medium": 2, "high": 3, "max": 4}
_LANGUAGES = {
    "en": 0, "nl": 1, "de": 2, "fr": 3, "no": 4, "cz": 5,
    "da": 6, "sv": 7, "es": 8, "pl": 9, "fi": 10, "et": 11,
}  # fmt: skip

AP_SELECTS: tuple[APSelectDescription, ...] = (
    APSelectDescription(
        key="channel",
        attribute="channel",
        choices=_CHANNELS,
        entity_category=EntityCategory.CONFIG,
    ),
    APSelectDescription(
        key="subghzchannel",
        attribute="subghz_channel",
        choices=_SUBGHZ,
        # Pointless on hardware without a sub-GHz radio.
        requires="has_sub_ghz",
        entity_category=EntityCategory.CONFIG,
    ),
    APSelectDescription(
        key="led",
        attribute="led_brightness",
        choices=_numbered("", _BRIGHTNESS),
        entity_category=EntityCategory.CONFIG,
    ),
    APSelectDescription(
        key="tft",
        attribute="tft_brightness",
        choices=_numbered("", _BRIGHTNESS),
        entity_category=EntityCategory.CONFIG,
    ),
    APSelectDescription(
        key="maxsleep",
        attribute="max_sleep",
        choices=_MAX_SLEEP,
        entity_category=EntityCategory.CONFIG,
    ),
    APSelectDescription(
        key="lock",
        attribute="lock",
        choices=_LOCK,
        entity_category=EntityCategory.CONFIG,
    ),
    APSelectDescription(
        key="wifipower",
        attribute="wifi_power",
        choices=_WIFI_POWER,
        entity_category=EntityCategory.CONFIG,
    ),
    APSelectDescription(
        key="language",
        attribute="language",
        choices=_LANGUAGES,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001  (signature fixed by Home Assistant)
    entry: OpenEPaperLinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Access Point selects the hardware actually supports."""
    coordinator = entry.runtime_data
    config = coordinator.ap_config

    async_add_entities(
        APSelect(coordinator, description)
        for description in AP_SELECTS
        if description.requires is None
        or (config is not None and getattr(config, description.requires, False))
    )


class APSelect(OpenEPaperLinkAPEntity, SelectEntity):
    """An Access Point setting chosen from a fixed set."""

    entity_description: APSelectDescription

    def __init__(
        self, coordinator: APCoordinator, description: APSelectDescription
    ) -> None:
        """Set up the select."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_options = list(description.choices)
        self._by_value = {value: name for name, value in description.choices.items()}

    @property
    def current_option(self) -> str | None:
        """Return the selected option, or None if the Access Point reports an
        unknown value."""
        config = self.coordinator.ap_config
        if config is None:
            return None
        return self._by_value.get(getattr(config, self.entity_description.attribute))

    async def async_select_option(self, option: str) -> None:
        """Write the selection to the Access Point."""
        await self.coordinator.async_set_ap_config_item(
            self.entity_description.key, self.entity_description.choices[option]
        )
