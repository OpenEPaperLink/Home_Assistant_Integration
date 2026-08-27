"""Buttons for tag commands and Access Point actions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from oepl import TagCommand

from .coordinator import APConfigEntry, APCoordinator
from .entity import OpenEPaperLinkAPEntity, OpenEPaperLinkTagEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class TagButtonDescription(ButtonEntityDescription):
    """Describes a button that sends a command to a tag."""

    command: TagCommand


@dataclass(frozen=True, kw_only=True)
class APButtonDescription(ButtonEntityDescription):
    """Describes a button that acts on the Access Point."""

    press_fn: Callable[[APCoordinator], Awaitable[None]]


TAG_BUTTONS: tuple[TagButtonDescription, ...] = (
    # These act on a tag rather than configuring one -- clearing a stuck
    # queue, forcing a redraw, rebooting, rescanning, putting it to sleep --
    # so they are diagnostic rather than config.
    TagButtonDescription(
        key="clear_pending",
        command=TagCommand.CLEAR,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TagButtonDescription(
        key="force_refresh",
        command=TagCommand.REFRESH,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TagButtonDescription(
        key="reboot_tag",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.DIAGNOSTIC,
        command=TagCommand.REBOOT,
    ),
    TagButtonDescription(
        key="scan_channels",
        entity_category=EntityCategory.DIAGNOSTIC,
        command=TagCommand.SCAN,
    ),
    TagButtonDescription(
        key="deep_sleep",
        entity_category=EntityCategory.DIAGNOSTIC,
        command=TagCommand.DEEPSLEEP,
    ),
)

AP_BUTTONS: tuple[APButtonDescription, ...] = (
    APButtonDescription(
        key="reboot_ap",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.DIAGNOSTIC,
        press_fn=lambda coordinator: coordinator.async_reboot_ap(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001  (signature fixed by Home Assistant)
    entry: APConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons for an Access Point and its tags."""
    coordinator = entry.runtime_data

    async_add_entities(APButton(coordinator, description) for description in AP_BUTTONS)

    known: set[str] = set()

    @callback
    def _async_add_new_tags() -> None:
        """Create buttons for tags that have appeared since the last check."""
        if new := set(coordinator.data) - known:
            known.update(new)
            async_add_entities(
                TagButton(coordinator, mac, description)
                for mac in new
                for description in TAG_BUTTONS
            )

    _async_add_new_tags()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_tags))


class TagButton(OpenEPaperLinkTagEntity, ButtonEntity):
    """Sends a command to a tag."""

    entity_description: TagButtonDescription

    def __init__(
        self, coordinator: APCoordinator, mac: str, description: TagButtonDescription
    ) -> None:
        """Set up the button."""
        super().__init__(coordinator, mac, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Send the command."""
        await self.coordinator.async_send_tag_command(
            self._mac, self.entity_description.command
        )


class APButton(OpenEPaperLinkAPEntity, ButtonEntity):
    """Performs an action on the Access Point."""

    entity_description: APButtonDescription

    def __init__(
        self, coordinator: APCoordinator, description: APButtonDescription
    ) -> None:
        """Set up the button."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Perform the action."""
        await self.entity_description.press_fn(self.coordinator)
