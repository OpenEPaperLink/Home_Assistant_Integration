"""Text entities for tag aliases and the Access Point name.

These are entities rather than options because the values live on the device
and the Access Point's own web interface can change them; an entity reflects
that, whereas stored options would go stale until the entry reloaded. Options
are reserved for preferences that exist only in Home Assistant.
"""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from oepl import OEPLError

from .const import DOMAIN
from .coordinator import APConfigEntry, APCoordinator
from .entity import OpenEPaperLinkAPEntity, OpenEPaperLinkTagEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001  (signature fixed by Home Assistant)
    entry: APConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up text entities for an Access Point and its tags."""
    coordinator = entry.runtime_data

    async_add_entities([APAliasText(coordinator)])

    known: set[str] = set()

    @callback
    def _async_add_new_tags() -> None:
        """Create an alias entity for newly seen tags."""
        if new := set(coordinator.data) - known:
            known.update(new)
            async_add_entities(TagAliasText(coordinator, mac) for mac in new)

    _async_add_new_tags()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_tags))


class TagAliasText(OpenEPaperLinkTagEntity, TextEntity):
    """The tag's display name, as stored on the Access Point."""

    _attr_mode = TextMode.TEXT
    _attr_native_max = 32
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: APCoordinator, mac: str) -> None:
        """Set up the entity."""
        super().__init__(coordinator, mac, "tag_alias")

    @property
    def native_value(self) -> str | None:
        """Return the current alias."""
        tag = self.tag
        return tag.alias if tag else None

    async def async_set_value(self, value: str) -> None:
        """Rename the tag on the Access Point."""
        try:
            await self.coordinator.client.set_alias(self._mac, value)
        except OEPLError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="tag_command_failed",
                translation_placeholders={"error": str(err)},
            ) from err


class APAliasText(OpenEPaperLinkAPEntity, TextEntity):
    """The Access Point's own name."""

    _attr_mode = TextMode.TEXT
    _attr_native_max = 32
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: APCoordinator) -> None:
        """Set up the entity."""
        super().__init__(coordinator, "alias")

    @property
    def native_value(self) -> str | None:
        """Return the current alias."""
        config = self.coordinator.ap_config
        return config.alias if config else None

    async def async_set_value(self, value: str) -> None:
        """Rename the Access Point."""
        await self.coordinator.async_set_ap_config_item("alias", value)
