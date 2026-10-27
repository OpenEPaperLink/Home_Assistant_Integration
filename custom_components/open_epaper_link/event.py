"""Event entities for tag button, NFC and GPIO wake-ups.

Replaces the pre-4.0 device triggers and their custom bus event.

Which entities a tag gets is decided from two sources, because neither is
sufficient alone:

- Buttons come from the tag type's ``options``. The runtime capability bit
  ``WAKE_BUTTON`` exists but is never set: a tag detects its capabilities
  electrically at boot and a button is not detectable that way.
- NFC comes from the capability bits, because ``options`` has no NFC token at
  all across any published tag type.

``options`` is also a statement about the model rather than the individual
unit -- the M2 and M3 series declare button support broadly while many units
ship without one. Button and GPIO entities are therefore created disabled and
enable themselves the first time a real event arrives.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from oepl import TagCapability

from .const import SIGNAL_TAG_INTERACTION
from .coordinator import APConfigEntry, APCoordinator
from .entity import OpenEPaperLinkTagEntity, async_remove_ap_display_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class TagEventDescription(EventEntityDescription):
    """Describes a kind of tag interaction."""

    # Created disabled when the hardware only might have it.
    speculative: bool = False


EVENT_TYPES: tuple[TagEventDescription, ...] = (
    TagEventDescription(
        key="button",
        # The firmware defines exactly two button wake reasons, and nothing
        # says how many a given unit actually has.
        event_types=["button1", "button2"],
        speculative=True,
    ),
    TagEventDescription(key="nfc", event_types=["nfc"]),
    TagEventDescription(key="gpio", event_types=["gpio"], speculative=True),
)


def _supported(coordinator: APCoordinator, mac: str, key: str) -> bool:
    """Whether *mac* should have an event entity of kind *key*."""
    if key == "gpio":
        # No tag type or capability bit describes GPIO wake-up. The Access
        # Point's built-in display never wakes up, so it is never one.
        return not coordinator.is_ap_display(mac)
    if key == "button":
        tag_type = coordinator.tag_type(mac)
        return bool(tag_type and tag_type.has_button)
    tag = coordinator.data.get(mac)
    if tag is None:
        return False
    return bool(tag.capability_flags & (TagCapability.NFC | TagCapability.NFC_WAKE))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: APConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up event entities per tag."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _async_add_new_tags() -> None:
        """Create event entities for newly seen tags."""
        if new := set(coordinator.data) - known:
            known.update(new)
            async_add_entities(
                TagEvent(coordinator, mac, description)
                for mac in new
                for description in EVENT_TYPES
                if _supported(coordinator, mac, description.key)
            )
            for mac in new:
                if coordinator.is_ap_display(mac):
                    async_remove_ap_display_entities(
                        hass, entry, mac, Platform.EVENT, ["gpio"]
                    )

    _async_add_new_tags()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_tags))


class TagEvent(OpenEPaperLinkTagEntity, EventEntity):
    """A kind of interaction reported by a tag."""

    entity_description: TagEventDescription

    def __init__(
        self, coordinator: APCoordinator, mac: str, description: TagEventDescription
    ) -> None:
        """Set up the entity."""
        super().__init__(coordinator, mac, description.key)
        self.entity_description = description
        if description.speculative:
            self._attr_entity_registry_enabled_default = False

    async def async_added_to_hass(self) -> None:
        """Subscribe to interactions for this tag."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_TAG_INTERACTION}_"
                f"{self.coordinator.config_entry.entry_id}_{self._mac}",
                self._handle_interaction,
            )
        )

    @callback
    def _handle_interaction(self, event_type: str) -> None:
        """Record an interaction of our kind."""
        if event_type not in (self.entity_description.event_types or ()):
            return
        self._trigger_event(event_type)
        self.async_write_ha_state()
