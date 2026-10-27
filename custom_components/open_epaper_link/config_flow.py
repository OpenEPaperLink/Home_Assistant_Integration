"""Config flow for OpenEPaperLink.

Discovery is the intended way in. The AP announces itself over DHCP as
``openepaperlink-*``, so in the normal case the user gets a discovered-device
card and clicks Add without typing an address. Manual entry remains for setups
where discovery cannot reach the AP, such as a separate VLAN.
"""

from __future__ import annotations

import logging
from typing import Any

import probatio as vol
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from oepl import OEPLClient, OEPLError, build_hostname
from py_atc_ble_oepl import (
    MANUFACTURER_ID,
    ATCDevice,
    ATCError,
    ATCProtocol,
)

from .const import (
    CONF_AP_MAC,
    CONF_HOST,
    CONF_MAC_ADDRESS,
    DEFAULT_BUTTON_DEBOUNCE,
    DEFAULT_NFC_DEBOUNCE,
    DOMAIN,
    OPT_BLACKLISTED_TAGS,
    OPT_BUTTON_DEBOUNCE,
    OPT_NFC_DEBOUNCE,
)
from .coordinator import APConfigEntry

_LOGGER = logging.getLogger(__name__)


class OpenEPaperLinkConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenEPaperLink."""

    VERSION = 5

    def __init__(self) -> None:
        """Initialise the flow."""
        self._host: str | None = None
        self._alias: str | None = None
        self._ap_mac: str | None = None
        self._atc_address: str | None = None
        self._atc_name: str | None = None

    # ------------------------------------------------------------------
    # Probing
    # ------------------------------------------------------------------

    async def _async_probe(self, host: str) -> tuple[str, str] | None:
        """Return (ap_mac, alias) for the AP at *host*, or None if unreachable.

        The MAC is the AP's identity: the host is mutable because DHCP moves
        it, whereas ``/sysinfo`` reports an empty alias and a ``sha`` that
        changes on every firmware update.
        """
        client = OEPLClient(host, session=async_get_clientsession(self.hass))
        try:
            info = await client.get_sysinfo()
            mac = await client.get_ap_mac()
        except OEPLError as err:
            _LOGGER.debug("Could not identify the AP at %s: %s", host, err)
            return None
        return dr.format_mac(mac), info.alias

    def _title(self) -> str:
        """Human-readable entry title.

        The Access Point's alias, or failing that the name it gives itself on
        the network -- py-oepl derives that from the MAC the way the firmware
        does. Deliberately not the address: DHCP moves it, and the title is
        set once at creation, so an address here is wrong from the first time
        the Access Point is handed a different one.
        """
        if self._alias:
            return self._alias
        if self._ap_mac:
            return build_hostname(self._ap_mac)
        return "OpenEPaperLink"

    # ------------------------------------------------------------------
    # DHCP discovery -- the primary path
    # ------------------------------------------------------------------

    @callback
    def _async_adopt_unmigrated_entry(self, mac: str, host: str) -> None:
        """Re-key a pre-4.0 entry for this Access Point onto its MAC.

        Entries added before 4.0 were keyed on the host, whichever way they
        were set up: both the manual step and DHCP discovery called
        ``async_set_unique_id(host)``. Migration replaces that with the MAC,
        but it needs the MAC from the Access Point, so it only runs once setup
        has succeeded -- and an unreachable Access Point retries indefinitely,
        leaving the old key in place for as long as it is down.

        A discovery arriving in that window would match nothing and add a
        second entry for hardware already configured. Discovery carries the
        MAC, so the re-key can happen here without a round trip.
        """
        for entry in self._async_current_entries():
            if entry.data.get(CONF_HOST) != host or entry.unique_id == mac:
                continue
            self.hass.config_entries.async_update_entry(
                entry, unique_id=mac, data={**entry.data, CONF_AP_MAC: mac}
            )
            _LOGGER.debug(
                "Re-keyed pre-4.0 entry %s onto %s before discovery",
                entry.entry_id,
                mac,
            )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle an AP discovered over DHCP."""
        mac = dr.format_mac(discovery_info.macaddress)
        self._async_adopt_unmigrated_entry(mac, discovery_info.ip)
        await self.async_set_unique_id(mac)
        # An AP that moved to a new address updates its entry rather than being
        # ignored, which is what keying on the host string used to prevent.
        #
        # reload_on_update=False because this entry already carries an update
        # listener that reloads. Doing both reloads twice and can race, which
        # Home Assistant deprecated in 2026.6 and rejects from 2026.12.
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: discovery_info.ip}, reload_on_update=False
        )

        # Deliberately no probe here: the announcement already carries the MAC
        # this entry is keyed on, and an Access Point that is briefly busy
        # should still be offered rather than silently dropped. Reachability is
        # verified when the user confirms.
        self._host = discovery_info.ip
        self._ap_mac = mac
        self.context["title_placeholders"] = {"name": self._title()}
        return await self.async_step_discovery_confirm()

    async def async_step_integration_discovery(
        self, discovery_info: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle a peer AP announced by an already-configured AP.

        Mesh members advertise each other, so adding the rest of a mesh is a
        click rather than a second manual entry.
        """
        host = discovery_info[CONF_HOST]
        probed = await self._async_probe(host)
        if probed is None:
            return self.async_abort(reason="cannot_connect")

        ap_mac, alias = probed
        await self.async_set_unique_id(ap_mac)
        # See async_step_dhcp: the update listener owns the reload.
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: host}, reload_on_update=False
        )

        self._host = host
        self._ap_mac = ap_mac
        self._alias = alias or discovery_info.get("alias")
        self.context["title_placeholders"] = {"name": self._title()}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered AP, verifying it answers first."""
        assert self._host is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            probed = await self._async_probe(self._host)
            if probed is None:
                errors["base"] = "cannot_connect"
            else:
                _, self._alias = probed
                return self.async_create_entry(
                    title=self._title(),
                    data={CONF_HOST: self._host, CONF_AP_MAC: self.unique_id},
                )

        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"name": self._title(), "host": self._host},
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Manual entry -- the fallback
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add an AP by address, for setups discovery cannot reach."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = _normalise_host(user_input[CONF_HOST])
            probed = await self._async_probe(host)
            if probed is None:
                errors["base"] = "cannot_connect"
            else:
                ap_mac, alias = probed
                await self.async_set_unique_id(ap_mac)
                # See async_step_dhcp: the update listener owns the reload.
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: host}, reload_on_update=False
                )
                self._host, self._alias, self._ap_mac = host, alias, ap_mac
                return self.async_create_entry(
                    title=self._title(),
                    data={CONF_HOST: host, CONF_AP_MAC: ap_mac},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): cv.string}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point an existing entry at a new address."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = _normalise_host(user_input[CONF_HOST])
            probed = await self._async_probe(host)
            if probed is None:
                errors["base"] = "cannot_connect"
            else:
                ap_mac, _ = probed
                await self.async_set_unique_id(ap_mac)
                # Refuse to repoint an entry at a different physical AP.
                self._abort_if_unique_id_mismatch(reason="wrong_ap")
                # Updating the entry wakes the update listener, which reloads.
                # Reloading here as well is the deprecated double reload.
                return self.async_update_and_abort(
                    entry, data_updates={CONF_HOST: host}
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST)): cv.string}
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Bluetooth discovery (ATC tags)
    # ------------------------------------------------------------------

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a tag running ATC firmware seen over Bluetooth."""
        await self.async_set_unique_id(dr.format_mac(discovery_info.address))
        self._abort_if_unique_id_configured()

        raw = discovery_info.manufacturer_data.get(MANUFACTURER_ID)
        if not raw:
            return self.async_abort(reason="not_supported")
        try:
            ATCProtocol.parse_advertising_data(raw)
        except ValueError:
            _LOGGER.debug("Unparseable advertisement from %s", discovery_info.address)
            return self.async_abort(reason="not_supported")
        # A receiver can attach a tag's advertisement to a neighbouring
        # device; one naming itself as something else is not the tag.
        if not ATCProtocol.is_device_name(discovery_info.name, discovery_info.address):
            _LOGGER.debug(
                "%s carries ATC data but is named %r",
                discovery_info.address,
                discovery_info.name,
            )
            return self.async_abort(reason="not_supported")

        self._atc_address = discovery_info.address
        # The name only arrives in the scan response, so it is often missing.
        self._atc_name = ATCProtocol.device_name(discovery_info.address)
        self.context["title_placeholders"] = {"name": self._atc_name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered tag, verifying it answers first.

        Discovery itself never connects -- it happens unprompted and would
        cost a sleeping tag a wake-up. Confirming is a deliberate act, so one
        connection here is worth it to fail now rather than at first upload.
        """
        assert self._atc_address is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            if await self._async_probe_atc(self._atc_address):
                return self.async_create_entry(
                    title=self._atc_name or self._atc_address,
                    data={CONF_MAC_ADDRESS: self._atc_address},
                )
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": self._atc_name or self._atc_address,
                "address": self._atc_address,
            },
            errors=errors,
        )

    async def _async_probe_atc(self, address: str) -> bool:
        """Return whether the tag at *address* can be reached right now."""
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, address, connectable=True
        )
        if ble_device is None:
            _LOGGER.debug("No connectable device for %s", address)
            return False
        try:
            async with ATCDevice(address, ble_device=ble_device):
                return True
        except ATCError as err:
            _LOGGER.debug("Could not reach tag %s: %s", address, err)
            return False

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: APConfigEntry,  # noqa: ARG004
    ) -> OpenEPaperLinkOptionsFlow:
        """Return the options flow."""
        return OpenEPaperLinkOptionsFlow()


class OpenEPaperLinkOptionsFlow(OptionsFlow):
    """Handle OpenEPaperLink options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        coordinator = getattr(self.config_entry, "runtime_data", None)
        known_tags = sorted(coordinator.data) if coordinator is not None else []

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        OPT_BLACKLISTED_TAGS,
                        default=list(options.get(OPT_BLACKLISTED_TAGS, [])),
                    ): cv.multi_select(known_tags),
                    vol.Optional(
                        OPT_BUTTON_DEBOUNCE,
                        default=options.get(
                            OPT_BUTTON_DEBOUNCE, DEFAULT_BUTTON_DEBOUNCE
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0, max=10)),
                    vol.Optional(
                        OPT_NFC_DEBOUNCE,
                        default=options.get(OPT_NFC_DEBOUNCE, DEFAULT_NFC_DEBOUNCE),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0, max=10)),
                }
            ),
        )


def _normalise_host(host: str) -> str:
    """Strip a scheme and trailing slashes from user-entered input."""
    host = host.strip()
    for scheme in ("http://", "https://"):
        if host.startswith(scheme):
            host = host[len(scheme) :]
    return host.rstrip("/")
