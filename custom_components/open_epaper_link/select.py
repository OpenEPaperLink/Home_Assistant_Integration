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
from oepl import APConfig

from .coordinator import APConfigEntry, APCoordinator
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


# Which values exist is py-oepl's business, taken from the firmware. What
# each one is called here is ours, because the option value is the entity
# state: deriving it from a display label would change recorder history the
# moment the label was reworded. test_select_keys_cover_the_library asserts
# the two stay in step, so a value added upstream fails here until it is
# named.
_KEYS: dict[str, dict[int, str]] = {
    "channel": {0: "auto", 11: "11", 15: "15", 20: "20", 25: "25", 26: "26"},
    "led": {0: "off", 15: "10", 31: "25", 127: "50", 191: "75", 255: "100"},
    "tft": {0: "off", 20: "10", 64: "25", 128: "50", 192: "75", 255: "100"},
    "maxsleep": {0: "shortest", 5: "5", 10: "10", 30: "30", 60: "60"},
    "lock": {0: "open", 1: "locked", 2: "learning"},
    "discovery": {0: "multicast", 1: "broadcast"},
    "wifipower": {
        8: "2_0", 20: "5_0", 28: "7_0", 34: "8_5", 44: "11_0", 52: "13_0",
        60: "15_0", 68: "17_0", 74: "18_5", 76: "19_0", 78: "19_5",
    },
    "language": {
        0: "en", 1: "nl", 2: "de", 3: "no", 4: "fr", 5: "cz",
        6: "sk", 7: "pl", 8: "es", 9: "sv", 10: "dk", 11: "et",
    },
    "subghzchannel": {
        0: "disabled",
        **{n: str(n) for n in (100, 101, 102, 103, 104, 105)},
        **{n: str(n) for n in (200, 201, 202, 203, 204, 205)},
    },
}  # fmt: skip

# The library value maps each set of keys describes.
LIBRARY_VALUES: dict[str, dict[int, str]] = {
    "channel": APConfig.CHANNELS,
    "led": APConfig.LED_BRIGHTNESS_LEVELS,
    "tft": APConfig.TFT_BRIGHTNESS_LEVELS,
    "maxsleep": APConfig.MAX_SLEEP_LEVELS,
    "lock": APConfig.LOCK_MODES,
    "discovery": APConfig.DISCOVERY_MODES,
    "wifipower": APConfig.WIFI_POWER_LEVELS,
    "language": APConfig.LANGUAGES,
    "subghzchannel": APConfig.SUBGHZ_CHANNELS,
}


def _choices(key: str) -> dict[str, int]:
    """Return option name to stored value for one setting."""
    return {name: value for value, name in _KEYS[key].items()}


AP_SELECTS: tuple[APSelectDescription, ...] = (
    APSelectDescription(
        key="channel",
        choices=_choices("channel"),
        attribute="channel",
        entity_category=EntityCategory.CONFIG,
    ),
    APSelectDescription(
        key="subghzchannel",
        choices=_choices("subghzchannel"),
        attribute="subghz_channel",
        # Pointless on hardware without a sub-GHz radio.
        requires="has_sub_ghz",
        entity_category=EntityCategory.CONFIG,
    ),
    APSelectDescription(
        key="led",
        choices=_choices("led"),
        attribute="led_brightness",
        entity_category=EntityCategory.CONFIG,
    ),
    APSelectDescription(
        key="tft",
        choices=_choices("tft"),
        attribute="tft_brightness",
        entity_category=EntityCategory.CONFIG,
    ),
    APSelectDescription(
        key="maxsleep",
        choices=_choices("maxsleep"),
        attribute="max_sleep",
        entity_category=EntityCategory.CONFIG,
    ),
    APSelectDescription(
        key="lock",
        choices=_choices("lock"),
        attribute="lock",
        entity_category=EntityCategory.CONFIG,
    ),
    APSelectDescription(
        key="wifipower",
        choices=_choices("wifipower"),
        attribute="wifi_power",
        entity_category=EntityCategory.CONFIG,
    ),
    APSelectDescription(
        key="language",
        choices=_choices("language"),
        attribute="language",
        entity_category=EntityCategory.CONFIG,
    ),
    APSelectDescription(
        key="discovery",
        choices=_choices("discovery"),
        attribute="discovery",
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001  (signature fixed by Home Assistant)
    entry: APConfigEntry,
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
