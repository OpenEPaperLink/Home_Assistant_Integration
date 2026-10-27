"""Firmware updates for the Access Point, its radio and its tags.

The Access Point decides nothing about updates itself: its update page asks
GitHub, and installs in a fixed order. py-oepl does both; these entities show
the result and run the install. Tags get their firmware through the Access
Point when they next check in.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from oepl import (
    OEPLError,
    Release,
    TagFirmware,
    UpdateProgress,
    UpdateStage,
    format_radio_version,
    format_tag_firmware_version,
)
from py_atc_ble_oepl import ATCError, ATCFirmware

from .atc_coordinator import (
    ATCConfigEntry,
    ATCFirmwareCoordinator,
    ATCRuntimeData,
    async_get_atc_firmware,
)
from .const import DOMAIN, TAG_UPDATE_LOCK
from .coordinator import (
    APConfigEntry,
    APCoordinator,
    AvailableFirmware,
    ReleaseCoordinator,
)
from .entity import ATCEntity, OpenEPaperLinkAPEntity, OpenEPaperLinkTagEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

# A tag running ATC firmware restarts into a new image a few seconds after
# storing it; it then advertises the new version.
_ATC_RESTART_TIMEOUT = 300

# The share of a firmware install each stage takes up, as (start, end) percent.
# Flashing dominates; the files are mostly unchanged and skipped.
_FIRMWARE_STAGES: dict[UpdateStage, tuple[int, int]] = {
    UpdateStage.FILESYSTEM: (0, 40),
    UpdateStage.TAG_TYPES: (40, 50),
    UpdateStage.FIRMWARE: (50, 100),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: APConfigEntry | ATCConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up update entities for an Access Point, or for an ATC tag."""
    if isinstance(entry.runtime_data, ATCRuntimeData):
        # Only over Bluetooth: an ATC tag an Access Point also lists gets no
        # update there, so one tag is never updated two ways.
        firmware = await async_get_atc_firmware(hass)
        async_add_entities([ATCFirmwareUpdate(entry, firmware)])
        return

    coordinator = entry.runtime_data
    releases = ReleaseCoordinator(hass, coordinator)
    # Not a first refresh: GitHub being unreachable must not keep the Access
    # Point from setting up, only leave the latest version unknown.
    await releases.async_refresh()

    entities: list[UpdateEntity] = [APFirmwareUpdate(coordinator, releases)]
    if coordinator.ap_info and coordinator.ap_info.radio_chip:
        entities.append(RadioFirmwareUpdate(coordinator, releases))
    async_add_entities(entities)

    known: set[str] = set()

    @callback
    def _async_add_tag_updates() -> None:
        """Add an update entity for each tag the repository has firmware for.

        Tags it has none for, such as those running ATC firmware, would only
        ever read as up to date.
        """
        data: AvailableFirmware | None = releases.data
        if data is None:
            return
        new = {
            mac
            for mac, firmware in data.tags.items()
            if firmware is not None and mac in coordinator.data
        } - known
        if new:
            known.update(new)
            async_add_entities(
                TagFirmwareUpdate(coordinator, releases, mac) for mac in new
            )

    _async_add_tag_updates()
    entry.async_on_unload(releases.async_add_listener(_async_add_tag_updates))


class _ReleaseUpdate(OpenEPaperLinkAPEntity, UpdateEntity):
    """Shared behaviour: installed version from the Access Point, latest from GitHub."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.RELEASE_NOTES
    )

    def __init__(
        self, coordinator: APCoordinator, releases: ReleaseCoordinator, key: str
    ) -> None:
        """Set up the entity."""
        super().__init__(coordinator, key)
        self.releases = releases

    async def async_added_to_hass(self) -> None:
        """Also follow the release checks."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.releases.async_add_listener(self._handle_coordinator_update)
        )

    @property
    def release(self) -> Release | None:
        """The newest release for this Access Point, if one was found."""
        data = self.releases.data
        return data.release if data else None

    @property
    def release_url(self) -> str | None:
        """Link to the release."""
        return self.release.url if self.release else None

    async def async_release_notes(self) -> str | None:
        """The release's notes, as written on GitHub."""
        return self.release.notes if self.release else None

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """Whether *latest_version* is an update.

        latest_version reads as the installed version unless the release is
        an update, which py-oepl decides the way the Access Point's page does.
        """
        return latest_version != installed_version

    @callback
    def _async_progress(self, percent: int | None) -> None:
        self._attr_in_progress = True
        self._attr_update_percentage = percent
        self.async_write_ha_state()

    async def _async_install(self, install: Awaitable[None]) -> None:
        """Run *install*, showing progress, and report a failure."""
        self._async_progress(None)
        try:
            await install
        except OEPLError as err:
            _LOGGER.warning("Updating %s failed: %s", self.entity_id, err)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        finally:
            self._attr_in_progress = False
            self._attr_update_percentage = None
            self.async_write_ha_state()


class APFirmwareUpdate(_ReleaseUpdate):
    """The Access Point's firmware and the web interface that goes with it."""

    _attr_title = "OpenEPaperLink"

    def __init__(
        self, coordinator: APCoordinator, releases: ReleaseCoordinator
    ) -> None:
        """Set up the entity."""
        super().__init__(coordinator, releases, "firmware")

    @property
    def installed_version(self) -> str | None:
        """The firmware the Access Point runs."""
        info = self.coordinator.ap_info
        return (info.build_version or None) if info else None

    @property
    def latest_version(self) -> str | None:
        """The newest release, or the installed version if that is not an update."""
        info, release = self.coordinator.ap_info, self.release
        if info is None or release is None:
            return self.installed_version if self.releases.data else None
        if release.is_update(info.build_version, _as_int(info.build_time)):
            return release.tag
        return info.build_version

    # The signature is Home Assistant's; there is one version to install.
    async def async_install(
        self,
        version: str | None,  # noqa: ARG002
        backup: bool,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        """Update the files, tag types and firmware. Reboots the Access Point."""
        release = self.release
        if release is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_release"
            )

        def on_progress(progress: UpdateProgress) -> None:
            start, end = _FIRMWARE_STAGES[progress.stage]
            share = (progress.percent or 0) * (end - start) // 100
            self._async_progress(start + share)

        await self._async_install(
            self.coordinator.client.updates.install(
                release,
                self.releases.env,
                repo=self.releases.repo,
                on_progress=on_progress,
            )
        )


class RadioFirmwareUpdate(_ReleaseUpdate):
    """The firmware of the Access Point's radio co-processor (ESP32-C6/H2)."""

    def __init__(
        self, coordinator: APCoordinator, releases: ReleaseCoordinator
    ) -> None:
        """Set up the entity."""
        super().__init__(coordinator, releases, "radio_firmware")

    @property
    def title(self) -> str | None:
        """Name the chip, as the Access Point's page does."""
        chip = self.coordinator.ap_info.radio_chip if self.coordinator.ap_info else None
        return f"ESP32-{chip}" if chip else None

    @property
    def installed_version(self) -> str | None:
        """The firmware the radio runs."""
        info = self.coordinator.ap_info
        version = info.radio_version if info else None
        return format_radio_version(version) if version else None

    @property
    def latest_version(self) -> str | None:
        """The release's radio firmware, or the installed one if not newer."""
        # None until a release check has succeeded, whatever the type says.
        data: AvailableFirmware | None = self.releases.data
        if data is None:
            return None
        info = self.coordinator.ap_info
        installed = info.radio_version if info else None
        latest = data.radio_version
        if latest is None or (installed and latest <= installed):
            return self.installed_version
        return format_radio_version(latest)

    # The signature is Home Assistant's; there is one version to install.
    async def async_install(
        self,
        version: str | None,  # noqa: ARG002
        backup: bool,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        """Flash the radio. The Access Point stays up, its radio offline meanwhile."""
        release, info = self.release, self.coordinator.ap_info
        if release is None or info is None or info.radio_chip is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_release"
            )

        def on_progress(progress: UpdateProgress) -> None:
            self._async_progress(progress.percent)

        await self._async_install(
            self.coordinator.client.updates.update_radio(
                release, info.radio_chip, on_progress=on_progress
            )
        )
        # Flashing the radio does not reboot the Access Point, so nothing else
        # would tell it the radio's version changed.
        await self.coordinator.async_refresh_ap_info()


class TagFirmwareUpdate(OpenEPaperLinkTagEntity, UpdateEntity):
    """A tag's firmware, which it fetches through the Access Point.

    A tag that fails part way through an update can need a tag flasher to
    recover, so tags are updated one at a time across every Access Point.
    """

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )

    def __init__(
        self, coordinator: APCoordinator, releases: ReleaseCoordinator, mac: str
    ) -> None:
        """Set up the entity."""
        super().__init__(coordinator, mac, "firmware")
        self.releases = releases

    async def async_added_to_hass(self) -> None:
        """Also follow the release checks."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.releases.async_add_listener(self._handle_coordinator_update)
        )

    @property
    def firmware(self) -> TagFirmware | None:
        """The newest firmware for this tag, if one was found."""
        data: AvailableFirmware | None = self.releases.data
        return data.tags.get(self._mac) if data else None

    @property
    def title(self) -> str | None:
        """The firmware, as the repository names it."""
        return self.firmware.name if self.firmware else None

    @property
    def installed_version(self) -> str | None:
        """The firmware the tag reports running."""
        tag = self.tag
        return format_tag_firmware_version(tag.firmware_version) if tag else None

    @property
    def latest_version(self) -> str | None:
        """The newest firmware, or the installed version if that is not newer."""
        tag, firmware = self.tag, self.firmware
        if tag is None or firmware is None:
            return self.installed_version
        if firmware.number > tag.firmware_version:
            return firmware.version
        return self.installed_version

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """Whether *latest_version* is an update; it reads as installed otherwise."""
        return latest_version != installed_version

    @callback
    def _async_progress(self, percent: int | None) -> None:
        self._attr_in_progress = True
        self._attr_update_percentage = percent
        self.async_write_ha_state()

    # The signature is Home Assistant's; there is one version to install.
    async def async_install(
        self,
        version: str | None,  # noqa: ARG002
        backup: bool,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        """Have the tag fetch and flash its firmware at its next check-in."""
        firmware = self.firmware
        if firmware is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_release"
            )
        lock = self.hass.data.setdefault(TAG_UPDATE_LOCK, asyncio.Lock())
        # Indeterminate while waiting its turn and for the tag to check in.
        self._async_progress(None)
        try:
            async with lock:
                await self.coordinator.client.updates.update_tag(
                    self._mac,
                    firmware,
                    repo=self.releases.repo,
                    on_progress=lambda p: self._async_progress(p.percent),
                )
        except OEPLError as err:
            _LOGGER.warning("Updating %s failed: %s", self.entity_id, err)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        finally:
            self._attr_in_progress = False
            self._attr_update_percentage = None
            self.async_write_ha_state()


class ATCFirmwareUpdate(ATCEntity, UpdateEntity):
    """The firmware of a tag running ATC firmware, updated over Bluetooth.

    atc1441 publishes one image for every such tag. A tag that fails part way
    through can need a wired flash to recover, so tags update one at a time,
    together with those behind Access Points.
    """

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )
    _attr_title = "ATC_BLE_OEPL"

    def __init__(self, entry: ATCConfigEntry, firmware: ATCFirmwareCoordinator) -> None:
        """Set up the entity."""
        super().__init__(
            entry.runtime_data.coordinator,
            entry.entry_id,
            UpdateEntityDescription(key="firmware", translation_key="firmware"),
        )
        self._runtime = entry.runtime_data
        self._firmware = firmware

    async def async_added_to_hass(self) -> None:
        """Also follow the firmware checks."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._firmware.async_add_listener(self._handle_coordinator_update)
        )

    @property
    def published(self) -> ATCFirmware | None:
        """The image atc1441 publishes, if it could be fetched."""
        firmware: ATCFirmware | None = self._firmware.data
        return firmware

    @property
    def installed_version(self) -> str | None:
        """The firmware the tag advertises running."""
        advertisement = self.advertisement
        if advertisement is None:
            return None
        return format_tag_firmware_version(advertisement.fw_version)

    @property
    def latest_version(self) -> str | None:
        """The published firmware, or the installed version if that is not newer."""
        published, advertisement = self.published, self.advertisement
        if published is None or published.version is None or advertisement is None:
            return None
        if published.version > advertisement.fw_version:
            return format_tag_firmware_version(published.version)
        return self.installed_version

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """Whether *latest_version* is an update; it reads as installed otherwise."""
        return latest_version != installed_version

    @callback
    def _async_progress(self, percent: int | None) -> None:
        self._attr_in_progress = True
        self._attr_update_percentage = percent
        self.async_write_ha_state()

    # The signature is Home Assistant's; there is one version to install.
    async def async_install(
        self,
        version: str | None,  # noqa: ARG002
        backup: bool,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        """Send the published firmware and wait for the tag to restart into it."""
        firmware = self.published
        if firmware is None or firmware.version is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_release"
            )
        lock = self.hass.data.setdefault(TAG_UPDATE_LOCK, asyncio.Lock())
        self._async_progress(None)
        device = self._runtime.device
        try:
            async with lock:
                async with device:
                    await device.update_firmware(
                        firmware,
                        progress_callback=lambda sent, total: self._async_progress(
                            sent * 100 // total
                        ),
                    )
                # Stored; it installs as it restarts, then advertises it.
                self._async_progress(None)
                await self._async_wait_for_version(firmware.version)
        except (ATCError, TimeoutError) as err:
            _LOGGER.warning("Updating %s failed: %s", self.entity_id, err)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err) or "no answer"},
            ) from err
        finally:
            self._attr_in_progress = False
            self._attr_update_percentage = None
            self.async_write_ha_state()

    async def _async_wait_for_version(self, version: int) -> None:
        """Wait until the tag advertises *version*.

        Raises:
            TimeoutError: If it has not within a few minutes, as when it
                refused the image and kept its own firmware.
        """
        reached = asyncio.Event()

        @callback
        def _check() -> None:
            advertisement = self.advertisement
            if advertisement is not None and advertisement.fw_version == version:
                reached.set()

        unsubscribe = self.coordinator.async_add_listener(_check)
        try:
            _check()
            async with asyncio.timeout(_ATC_RESTART_TIMEOUT):
                await reached.wait()
        finally:
            unsubscribe()


def _as_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0
