"""Coordinator for an OpenEPaperLink Access Point."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from oepl import (
    APInfo,
    APStatus,
    OEPLClient,
    OEPLError,
    Tag,
    TagType,
    WakeupReason,
)

from .const import (
    CONF_AP_MAC,
    CONF_HOST,
    DOMAIN,
    OPT_BLACKLISTED_TAGS,
    OPT_BUTTON_DEBOUNCE,
    OPT_NFC_DEBOUNCE,
    SIGNAL_ENTRIES_CHANGED,
    SIGNAL_TAG_INTERACTION,
)

if TYPE_CHECKING:
    from .runtime_data import OpenEPaperLinkConfigEntry

_LOGGER = logging.getLogger(__name__)

# Wake-up reasons surfaced as event entity events. The firmware defines exactly
# two button reasons, so this is the complete set; the pre-4.0 integration
# advertised BUTTON1-10, which had no basis in the protocol.
_INTERACTION_WAKEUP_REASONS: dict[int, str] = {
    WakeupReason.GPIO: "gpio",
    WakeupReason.NFC: "nfc",
    WakeupReason.BUTTON1: "button1",
    WakeupReason.BUTTON2: "button2",
}


class APCoordinator(DataUpdateCoordinator[dict[str, Tag]]):
    """Push-driven coordinator for one Access Point.

    The AP pushes over a WebSocket, so there is no polling interval. py-oepl
    owns the connection, its reconnect loop and the tag cache; this class
    translates those callbacks into Home Assistant state.

    One coordinator per config entry, one config entry per AP. Mesh setups add
    an entry per AP and each claims a disjoint set of tags -- see
    :meth:`owns_tag`.
    """

    config_entry: OpenEPaperLinkConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry
    ) -> None:
        """Set up the coordinator without contacting the AP."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.data[CONF_HOST]}",
            config_entry=entry,
            update_interval=None,  # push-driven
        )
        self.host: str = entry.data[CONF_HOST]
        self.ap_mac: str = entry.data[CONF_AP_MAC]
        self.client = OEPLClient(self.host, session=async_get_clientsession(hass))

        self.ap_info: APInfo | None = None
        self.ap_status: APStatus | None = None
        self.online = False

        self._tag_types: dict[int, TagType | None] = {}
        self._known_tags: set[str] = set()
        self._last_trigger: dict[tuple[str, str], datetime] = {}
        self._unsubs: list[Any] = []

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------

    @property
    def blacklisted_tags(self) -> set[str]:
        """MACs the user has chosen to hide, uppercased."""
        raw = self.config_entry.options.get(OPT_BLACKLISTED_TAGS, [])
        return {str(mac).upper() for mac in raw}

    def _debounce_for(self, trigger_type: str) -> timedelta:
        """Return the debounce window for a trigger type."""
        options = self.config_entry.options
        if trigger_type == "nfc":
            seconds = options.get(OPT_NFC_DEBOUNCE, 1.0)
        else:
            seconds = options.get(OPT_BUTTON_DEBOUNCE, 0.5)
        return timedelta(seconds=float(seconds))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Fetch initial state and open the WebSocket.

        Raises ConfigEntryNotReady if the AP cannot be reached, so Home
        Assistant retries with backoff rather than leaving a broken entry.
        """
        try:
            self.ap_info = await self.client.get_sysinfo()
            tags = await self.client.get_tags()
        except OEPLError as err:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="ap_cannot_connect",
                translation_placeholders={"host": self.host},
            ) from err

        self.async_set_updated_data(self._visible_tags(tags))

        self._unsubs = [
            self.client.on_tag_update(self._handle_tag_update),
            self.client.on_ap_status(self._handle_ap_status),
            self.client.on_connection_change(self._handle_connection_change),
            self.client.on_ap_item(self._handle_ap_item),
        ]
        await self.client.connect()

    async def async_shutdown(self) -> None:
        """Close the WebSocket and drop callbacks."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self.client.disconnect()
        await super().async_shutdown()

    # ------------------------------------------------------------------
    # Tag ownership (mesh)
    # ------------------------------------------------------------------

    def owns_tag(self, tag: Tag) -> bool:
        """Return True if this entry should expose *tag*.

        Every AP in a mesh reports its peers' tags too, flagged ``isexternal``
        with ``apip`` naming the owner. Filtering all external tags would hide
        them entirely from someone who only added one AP of several, so an
        entry claims a tag unless some *other loaded entry* owns it natively.
        """
        if not tag.is_external:
            return True
        return not self._other_entry_owns(tag.ap_ip)

    def _other_entry_owns(self, ap_ip: str) -> bool:
        """Return True if another loaded entry is the AP at *ap_ip*."""
        if not ap_ip:
            return False
        for entry in self.hass.config_entries.async_loaded_entries(DOMAIN):
            if entry.entry_id == self.config_entry.entry_id:
                continue
            if entry.data.get(CONF_HOST) == ap_ip:
                return True
        return False

    def _visible_tags(self, tags: list[Tag]) -> dict[str, Tag]:
        """Filter *tags* down to the ones this entry exposes."""
        blacklist = self.blacklisted_tags
        return {
            tag.mac: tag
            for tag in tags
            if tag.mac not in blacklist and self.owns_tag(tag)
        }

    @callback
    def async_reevaluate_ownership(self) -> None:
        """Re-run the ownership rule after a sibling entry loaded or unloaded."""
        self.async_set_updated_data(self._visible_tags(list(self.client.tags.values())))

    # ------------------------------------------------------------------
    # WebSocket callbacks
    # ------------------------------------------------------------------

    @callback
    def _handle_tag_update(self, tag: Tag) -> None:
        """Handle a pushed tag update."""
        if tag.mac in self.blacklisted_tags or not self.owns_tag(tag):
            self.data.pop(tag.mac, None)
            self.async_update_listeners()
            return

        previous = self.data.get(tag.mac)
        self.data[tag.mac] = tag

        if previous is None and tag.mac not in self._known_tags:
            self._known_tags.add(tag.mac)
            _LOGGER.debug("Discovered tag %s", tag.mac)

        if previous is not None and previous.alias != tag.alias:
            self._async_sync_device_name(tag)

        self._async_fire_trigger_event(tag)
        self.async_update_listeners()

    @callback
    def _handle_ap_status(self, status: APStatus) -> None:
        """Handle a pushed AP status message."""
        self.ap_status = status
        self.async_update_listeners()

    @callback
    def _handle_connection_change(self, connected: bool) -> None:
        """Handle the WebSocket connecting or dropping."""
        if connected == self.online:
            return
        self.online = connected
        if not connected:
            _LOGGER.warning("Lost connection to AP at %s", self.host)
        self.async_update_listeners()

    @callback
    def _handle_ap_item(self, item: Any) -> None:
        """Handle a peer AP announcement by raising a discovery flow."""
        ip = getattr(item, "ip", "")
        if not ip or ip == self.host:
            return
        if any(
            entry.data.get(CONF_HOST) == ip
            for entry in self.hass.config_entries.async_entries(DOMAIN)
        ):
            return
        self.hass.async_create_task(
            self.hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "integration_discovery"},
                data={CONF_HOST: ip, "alias": getattr(item, "alias", "")},
            )
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    @callback
    def _async_fire_trigger_event(self, tag: Tag) -> None:
        """Fire a bus event for button/NFC/GPIO wake-ups, debounced.

        The AP resends the same wake-up reason on repeated check-ins, so
        without debouncing a single button press can fire several times.
        """
        trigger_type = _INTERACTION_WAKEUP_REASONS.get(tag.wakeup_reason)
        if trigger_type is None:
            return

        key = (tag.mac, trigger_type)
        now = dt_util.utcnow()
        last = self._last_trigger.get(key)
        if last is not None and now - last < self._debounce_for(trigger_type):
            return
        self._last_trigger[key] = now

        async_dispatcher_send(
            self.hass,
            f"{SIGNAL_TAG_INTERACTION}_{self.config_entry.entry_id}_{tag.mac}",
            trigger_type,
        )

    @callback
    def _async_sync_device_name(self, tag: Tag) -> None:
        """Mirror an alias change from the AP into the device registry."""
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(
            identifiers={(DOMAIN, f"{self.config_entry.entry_id}_{tag.mac}")}
        )
        if device is not None:
            registry.async_update_device(device.id, name=tag.alias or tag.mac)

    # ------------------------------------------------------------------
    # Tag types
    # ------------------------------------------------------------------

    async def async_get_tag_type(self, hw_type: int) -> TagType | None:
        """Return the tag type definition for *hw_type*.

        Served by the AP itself. The AP reads the same file to render to a tag
        at all, so a miss means a genuine fault rather than a coverage gap.
        """
        if hw_type not in self._tag_types:
            try:
                self._tag_types[hw_type] = await self.client.get_tag_type(hw_type)
            except OEPLError as err:
                _LOGGER.warning("Could not load tag type 0x%02X: %s", hw_type, err)
                return None
            if self._tag_types[hw_type] is None:
                _LOGGER.warning(
                    "AP has no tag type definition for 0x%02X", hw_type
                )
        return self._tag_types[hw_type]


@callback
def async_notify_entries_changed(hass: HomeAssistant) -> None:
    """Tell loaded entries to re-evaluate mesh tag ownership."""
    async_dispatcher_send(hass, SIGNAL_ENTRIES_CHANGED)
