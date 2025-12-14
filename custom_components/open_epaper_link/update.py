from __future__ import annotations

from datetime import datetime, timedelta
import logging

from awesomeversion import AwesomeVersion
from homeassistant.components.labs import async_is_preview_feature_enabled, async_listen
from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .ble import BLEDeviceMetadata
from .const import DOMAIN
from .entity import OpenEPaperLinkBLEEntity
from .runtime_data import OpenEPaperLinkBLERuntimeData
from .util import is_ble_entry

_LOGGER = logging.getLogger(__name__)

GITHUB_LATEST_URL = "https://api.github.com/repos/OpenEPaperLink/OEPL_BLE/releases/latest"
DEFAULT_RELEASE_URL = "https://github.com/OpenEPaperLink/OEPL_BLE/releases"
CACHE_DURATION = timedelta(hours=6)


async def async_setup_entry(
        hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OEPL BLE firmware update entity for BLE entries when Labs is enabled."""
    entry_data = entry.runtime_data
    if not is_ble_entry(entry_data):
        return

    added: dict[str, OeplBleUpdateEntity] = {}

    async def _remove_entity(entity: "OeplBleUpdateEntity") -> None:
        await entity.async_remove()
        if entity.entity_id:
            from homeassistant.helpers import entity_registry as er

            er.async_get(hass).async_remove(entity.entity_id)

    @callback
    def _sync_feature_state() -> None:
        enabled = async_is_preview_feature_enabled(hass, DOMAIN, "oepl_ble_updates")

        if enabled and entry.entry_id not in added:
            metadata = BLEDeviceMetadata(entry_data.device_metadata or {})
            if not metadata.is_oepl:
                _LOGGER.debug(
                    "Skipping update entity for %s (not OEPL)", entry_data.mac_address
                )
                return  # OEPL-only
            _LOGGER.debug(
                "Enabling OEPL BLE update entity for %s", entry_data.mac_address
            )
            entity = OeplBleUpdateEntity(hass, entry, entry_data)
            added[entry.entry_id] = entity
            async_add_entities([entity])
            return

        if not enabled and (entity := added.pop(entry.entry_id, None)):
            _LOGGER.debug(
                "Labs disabled; removing OEPL BLE update entity for %s",
                entry_data.mac_address,
            )
            hass.async_create_task(_remove_entity(entity))

    # Listen for Labs toggle
    entry.async_on_unload(
        async_listen(hass, DOMAIN, "oepl_ble_updates", _sync_feature_state)
    )

    # Apply current state
    _sync_feature_state()


class OeplBleUpdateEntity(OpenEPaperLinkBLEEntity, UpdateEntity):
    """Firmware update indicator for OEPL BLE tags."""

    _attr_has_entity_name = True
    _attr_translation_key = "oepl_ble_firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_supported_features = UpdateEntityFeature.RELEASE_NOTES
    _attr_should_poll = True
    _attr_entity_registry_enabled_default = True

    def __init__(
            self,
            hass: HomeAssistant,
            entry,
            runtime_data: OpenEPaperLinkBLERuntimeData,
    ) -> None:
        self.hass = hass
        self._entry_data = runtime_data
        self._entry = entry
        self._latest_version: str | None = None
        self._release_url: str | None = None
        self._release_notes: str | None = None
        self._last_checked: datetime | None = None
        self._last_fetch_error: str | None = None
        self._mac = runtime_data.mac_address
        self._name = runtime_data.name
        self._session = async_get_clientsession(hass)
        super().__init__(self._mac, self._name, entry)
        self._attr_unique_id = f"oepl_ble_{self._mac}_firmware_update"
        self._attr_installed_version = self._compute_installed_version()

    @property
    def available(self) -> bool:
        """Keep the update entity available even if the tag is offline."""
        return True

    def _compute_installed_version(self) -> str | None:
        metadata_dict = self._entry_data.device_metadata or {}
        metadata = BLEDeviceMetadata(metadata_dict)
        fw = metadata.fw_version
        if fw not in ("", 0, None):
            _LOGGER.debug("Firmware from metadata for %s: %s", self._mac, fw)
            return str(fw)

        from homeassistant.helpers import device_registry as dr

        device_registry = dr.async_get(self.hass)
        device = device_registry.async_get_device(
            identifiers={(DOMAIN, f"ble_{self._mac}")},
        )
        if device and device.sw_version and device.sw_version.lower() != "unknown":
            _LOGGER.debug(
                "Firmware from device registry for %s: %s",
                self._mac,
                device.sw_version,
            )
            return device.sw_version

        _LOGGER.debug(
            "No firmware version available for %s; metadata=%s registry=%s",
            self._mac,
            metadata_dict,
            device.sw_version if device else None,
        )
        return None

    @property
    def installed_version(self) -> str | None:
        return self._attr_installed_version

    @property
    def latest_version(self) -> str | None:
        return self._latest_version

    @property
    def release_url(self) -> str | None:
        return self._release_url or DEFAULT_RELEASE_URL

    async def async_release_notes(self) -> str | None:
        return self._release_notes

    async def async_added_to_hass(self) -> None:
        # Ensure we have fresh installed_version and fetch latest once on add
        self._attr_installed_version = self._compute_installed_version()
        await self.async_update()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh installed_version (in case metadata changed) and latest version from GitHub (cached)."""
        self._attr_installed_version = self._compute_installed_version()

        now = datetime.utcnow()
        if self._last_checked and now - self._last_checked < CACHE_DURATION:
            return

        try:
            async with self._session.get(
                    GITHUB_LATEST_URL,
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "HomeAssistant-OEPL-BLE-update-entity",
                    },
                    raise_for_status=True,
            ) as resp:
                data = await resp.json()

            tag = data.get("tag_name") or data.get("name")
            if not tag:
                _LOGGER.debug("No tag_name/name in GitHub response for %s", self._mac)
                return

            normalized = tag[1:] if tag.startswith("v") else tag
            self._latest_version = normalized
            self._release_url = data.get("html_url") or DEFAULT_RELEASE_URL
            self._release_notes = data.get("body")
            self._last_checked = now
            self._last_fetch_error = None
        except Exception as err:
            msg = str(err)
            if msg != self._last_fetch_error:
                _LOGGER.error("Failed to fetch OEPL BLE latest version: %s", msg)
                self._last_fetch_error = msg
            else:
                _LOGGER.debug("Failed to fetch OEPL BLE latest version: %s", msg)

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """Use AwesomeVersion for comparison."""
        try:
            return AwesomeVersion(latest_version) > AwesomeVersion(installed_version)
        except Exception:
            return latest_version != installed_version