"""Config flow for OpenEPaperLink.

Discovery is the intended way in. The AP announces itself over DHCP as
``openepaperlink-*``, so in the normal case the user gets a discovered-device
card and clicks Add without typing an address. Manual entry remains for setups
where discovery cannot reach the AP, such as a separate VLAN.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
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
from oepl import OEPLClient, OEPLError
from py_atc_ble_oepl import (
    MANUFACTURER_ID,
    AdvertisingData,
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
            wifi = await client.get_wifi_config()
        except OEPLError as err:
            _LOGGER.debug("Could not reach AP at %s: %s", host, err)
            return None

        if not wifi.mac:
            _LOGGER.debug("AP at %s reported no MAC address", host)
            return None
        return dr.format_mac(wifi.mac), info.alias

    def _title(self) -> str:
        """Human-readable entry title."""
        return self._alias or f"OpenEPaperLink {self._host}"

    # ------------------------------------------------------------------
    # DHCP discovery -- the primary path
    # ------------------------------------------------------------------

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle an AP discovered over DHCP."""
        await self.async_set_unique_id(dr.format_mac(discovery_info.macaddress))
        # An AP that moved to a new address updates its entry rather than being
        # ignored, which is what keying on the host string used to prevent.
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.ip})

        # Deliberately no probe here: the announcement already carries the MAC
        # this entry is keyed on, and an Access Point that is briefly busy
        # should still be offered rather than silently dropped. Reachability is
        # verified when the user confirms.
        self._host = discovery_info.ip
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
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._host = host
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
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                self._host, self._alias = host, alias
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
                return self.async_update_reload_and_abort(
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
            advertisement = ATCProtocol.parse_advertising_data(raw)
        except ValueError:
            _LOGGER.debug("Unparseable advertisement from %s", discovery_info.address)
            return self.async_abort(reason="not_supported")

        self._atc_address = discovery_info.address
        self._atc_name = _atc_name(discovery_info, advertisement)
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


def _atc_name(
    discovery_info: BluetoothServiceInfoBleak, advertisement: AdvertisingData
) -> str:
    """Return a human-readable name for a discovered tag.

    Home Assistant reports the address as the name when a device advertises
    none, which is common for these tags. Falling back to the hardware type
    plus the last two address octets is more use than a bare MAC.
    """
    name = discovery_info.name
    if name and name != discovery_info.address:
        return name
    suffix = discovery_info.address.replace(":", "")[-4:]
    return f"ATC {advertisement.hw_type:02X} ({suffix})"
