"""Coordinator for an OpenEPaperLink Access Point."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from oepl import (
    APConfig,
    APInfo,
    APStatus,
    OEPLClient,
    OEPLError,
    Tag,
    TagCommand,
    TagType,
    WakeupReason,
)

from .const import (
    CONF_AP_MAC,
    CONF_HOST,
    DEFAULT_BUTTON_DEBOUNCE,
    DEFAULT_NFC_DEBOUNCE,
    DOMAIN,
    OPT_BLACKLISTED_TAGS,
    OPT_BUTTON_DEBOUNCE,
    OPT_NFC_DEBOUNCE,
    SIGNAL_ENTRIES_CHANGED,
    SIGNAL_TAG_INTERACTION,
)

_LOGGER = logging.getLogger(__name__)

type OpenEPaperLinkConfigEntry = ConfigEntry[APCoordinator]

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

    def __init__(self, hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry) -> None:
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
        self.ap_config: APConfig | None = None
        self.ap_status: APStatus | None = None
        self.online = False

        self._tag_types: dict[int, TagType | None] = {}
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
            seconds = options.get(OPT_NFC_DEBOUNCE, DEFAULT_NFC_DEBOUNCE)
        else:
            seconds = options.get(OPT_BUTTON_DEBOUNCE, DEFAULT_BUTTON_DEBOUNCE)
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
            self.ap_config = await self.client.get_ap_config()
            tags = await self.client.get_tags()
        except OEPLError as err:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="ap_cannot_connect",
                translation_placeholders={"host": self.host, "error": str(err)},
            ) from err

        # The round trip above proves the Access Point is reachable. Waiting
        # for the WebSocket to report a connection instead would leave every
        # entity unavailable until it opens, and permanently so on a setup
        # where HTTP works but the socket does not.
        self.online = True

        visible = self._visible_tags(tags)
        # Entities read tag geometry and hardware names synchronously when
        # building device info, so the definitions have to be in hand first.
        await self._async_prefetch_tag_types(visible.values())
        self.async_set_updated_data(visible)

        self._unsubs = [
            self.client.on_tag_update(self._handle_tag_update),
            self.client.on_ap_status(self._handle_ap_status),
            self.client.on_connection_change(self._handle_connection_change),
            self.client.on_ap_item(self._handle_ap_item),
            # A sibling entry loading or unloading changes which of us owns a
            # mesh tag, and that is not something the AP tells us about.
            async_dispatcher_connect(
                self.hass, SIGNAL_ENTRIES_CHANGED, self.async_reevaluate_ownership
            ),
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
        """Return True if another active entry is the Access Point at *ap_ip*.

        An entry setting up counts as active: it announces itself at the end of
        its own setup, before Home Assistant has marked it loaded, and it
        plainly owns its own tags by then.
        """
        if not ap_ip:
            return False
        return any(
            entry.entry_id != self.config_entry.entry_id
            and entry.data.get(CONF_HOST) == ap_ip
            and entry.state
            in (ConfigEntryState.LOADED, ConfigEntryState.SETUP_IN_PROGRESS)
            for entry in self.hass.config_entries.async_entries(DOMAIN)
        )

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

        if previous is None:
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
    # Access Point configuration
    # ------------------------------------------------------------------

    async def async_set_ap_config_item(self, key: str, value: str | int | bool) -> None:
        """Change one Access Point setting and refresh the cached config."""
        try:
            await self.client.set_ap_config_item(key, value)
            self.ap_config = await self.client.get_ap_config()
        except OEPLError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="ap_command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self.async_update_listeners()

    async def async_send_tag_command(self, mac: str, command: TagCommand) -> None:
        """Send a command to a tag, surfacing failures to the user."""
        try:
            await self.client.send_tag_cmd(mac, command)
        except OEPLError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="tag_command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_reboot_ap(self) -> None:
        """Reboot the Access Point."""
        try:
            await self.client.reboot_ap()
        except OEPLError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="ap_command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_refresh_ap_config(self) -> None:
        """Re-read the Access Point configuration."""
        try:
            self.ap_config = await self.client.get_ap_config()
        except OEPLError as err:
            _LOGGER.warning("Could not refresh AP config: %s", err)
            return
        self.async_update_listeners()

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

        # A speculative entity only exists disabled until something proves the
        # hardware is really there, so enable it before dispatching.
        self._async_enable_speculative_entity(tag.mac, trigger_type)
        async_dispatcher_send(
            self.hass,
            f"{SIGNAL_TAG_INTERACTION}_{self.config_entry.entry_id}_{tag.mac}",
            trigger_type,
        )

    @callback
    def _async_enable_speculative_entity(self, mac: str, event_type: str) -> None:
        """Enable a disabled event entity once it fires for real.

        Button and GPIO entities are created disabled, because a tag type
        declaring button support describes the model rather than the unit in
        hand. A real event proves the hardware is there.

        Only entities this integration disabled are touched, so a user who
        deliberately turned one off is never overridden. This mirrors the
        precedent in Home Assistant's own device_tracker component.
        """
        entry = self.config_entry
        if entry.pref_disable_new_entities:
            return

        key = "button" if event_type.startswith("button") else event_type
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id(
            "event", DOMAIN, f"{entry.entry_id}_{mac}_{key}"
        )
        if entity_id is None:
            return

        record = registry.async_get(entity_id)
        if (
            record is None
            or record.disabled_by is not er.RegistryEntryDisabler.INTEGRATION
        ):
            return

        _LOGGER.debug("Enabling %s after a real %s event", entity_id, event_type)
        registry.async_update_entity(entity_id, disabled_by=None)

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
                _LOGGER.warning("AP has no tag type definition for 0x%02X", hw_type)
        return self._tag_types[hw_type]

    async def _async_prefetch_tag_types(self, tags: Iterable[Tag]) -> None:
        """Load the tag type for every distinct hardware type in *tags*."""
        for hw_type in {tag.hw_type for tag in tags}:
            await self.async_get_tag_type(hw_type)

    @callback
    def tag_type(self, mac: str) -> TagType | None:
        """Return the cached tag type for *mac*, without fetching."""
        tag = self.data.get(mac)
        return self._tag_types.get(tag.hw_type) if tag else None

    @callback
    def tag_type_name(self, mac: str) -> str | None:
        """Return the hardware name for *mac*, for the device registry."""
        tag_type = self.tag_type(mac)
        return tag_type.name if tag_type else None
