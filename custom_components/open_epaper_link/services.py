"""Actions for the OpenEPaperLink integration.

The declarative renderer behind ``drawcustom`` lives in odl-renderer, which has
no Home Assistant coupling of its own. What stays here is the part that
genuinely needs Home Assistant: recorder history for plots, font locations and
path validation.

``drawcustom`` and ``setled`` payloads are hand-written YAML living in people's
automations, so unlike the rest of this rewrite these actions keep accepting
the pre-4.0 call shape and coerce it.
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

import voluptuous as vol
from epaper_dithering import ColorScheme, DitherMode
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service import async_extract_entity_ids
from odl_renderer import generate_image
from oepl import LUT, Color, LEDPattern, LEDSegment, TagCommand, TagType

from .const import DOMAIN, OPT_CUSTOM_FONT_DIRS
from .coordinator import APCoordinator

_LOGGER = logging.getLogger(__name__)

# Commands that act on a single tag. Each was also a service before 4.0 and
# stays one, because automations call them.
TAG_COMMAND_SERVICES = {
    "clear_pending": TagCommand.CLEAR,
    "force_refresh": TagCommand.REFRESH,
    "reboot_tag": TagCommand.REBOOT,
    "scan_channels": TagCommand.SCAN,
}

_TARGET_FIELDS = {
    vol.Optional("entity_id", default=[]): cv.entity_ids_or_uuids,
    vol.Optional("device_id", default=[]): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional("area_id", default=[]): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional("label_id", default=[]): vol.All(cv.ensure_list, [cv.string]),
}


# ---------------------------------------------------------------------------
# Value coercion
# ---------------------------------------------------------------------------


def _refresh_type(value: Any) -> LUT:
    """Accept refresh names and the pre-4.0 numeric values.

    The old numbers meant something other than their labels implied: "0" was
    labelled Full and stores the value that forces a full waveform on every
    update. An explicit old value keeps its old meaning; only the default
    changes.
    """
    legacy = {
        "0": LUT.NO_REPEAT,  # was labelled "Full"
        "1": LUT.FAST,
        "2": LUT.FAST_NO_REDS,
        "3": LUT.DEFAULT,
    }
    names = {
        "adaptive": LUT.DEFAULT,
        "full": LUT.NO_REPEAT,
        "fast": LUT.FAST,
        "fast_no_red": LUT.FAST_NO_REDS,
    }
    text = str(value).strip().lower()
    # Checked against None rather than truthiness: LUT.DEFAULT is 0.
    if (result := legacy.get(text, names.get(text))) is not None:
        return result
    raise vol.Invalid(f"Invalid refresh_type: {value}")


def _dither(value: Any) -> DitherMode:
    """Accept any epaper-dithering mode name, and the pre-4.0 numbers.

    Dithering is done here rather than on the Access Point, so the whole set
    of algorithms is available instead of the three it offers. The old numbers
    named those three.
    """
    legacy = {"0": DitherMode.NONE, "1": DitherMode.BURKES, "2": DitherMode.ORDERED}
    text = str(value).strip().lower()
    if text in legacy:
        return legacy[text]
    try:
        return DitherMode[text.upper()]
    except KeyError:
        raise vol.Invalid(
            f"Invalid dither: {value}. Expected one of "
            + ", ".join(mode.name.lower() for mode in DitherMode)
        ) from None


def _color_scheme(tag_type: TagType) -> ColorScheme:
    """Return the palette to dither for, from the tag's colour table."""
    table = tag_type.color_table or {}
    match "red" in table, "yellow" in table:
        case True, True:
            return ColorScheme.BWRY
        case True, False:
            return ColorScheme.BWR
        case False, True:
            return ColorScheme.BWY
        case _:
            return ColorScheme.MONO


def _accent_color(tag_type: TagType) -> str:
    """Return the colour odl-renderer should draw accents in.

    A two-colour tag has no accent, so black is the only honest answer.
    """
    table = tag_type.color_table or {}
    return next((name for name in ("red", "yellow") if name in table), "black")


_RGB = vol.All(cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min=0, max=255))])
_SECONDS = vol.All(vol.Coerce(float), vol.Range(min=0, max=25.5))
_FLASH_SPEED = vol.All(vol.Coerce(float), vol.Range(min=0, max=1.5))
_FLASH_COUNT = vol.All(vol.Coerce(int), vol.Range(min=0, max=15))


def _led_segment_fields(index: int, color: list[int], delay: float) -> dict:
    """Return the schema fields for one of the three LED groups."""
    return {
        vol.Optional(f"color{index}", default=color): _RGB,
        vol.Optional(f"flash_speed{index}", default=0.2): _FLASH_SPEED,
        vol.Optional(f"flash_count{index}", default=2): _FLASH_COUNT,
        vol.Optional(f"delay{index}", default=delay): _SECONDS,
    }


SCHEMA_DRAWCUSTOM = vol.Schema(
    {
        **_TARGET_FIELDS,
        vol.Required("payload"): vol.All(cv.ensure_list, [dict]),
        vol.Optional("background", default="white"): cv.string,
        vol.Optional("rotate", default=0): vol.All(
            vol.Coerce(int), vol.In([0, 90, 180, 270])
        ),
        vol.Optional("dither", default="ordered"): _dither,
        vol.Optional("ttl", default=60): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional("refresh_type", default="adaptive"): _refresh_type,
        # Hyphenated, as the pre-4.0 action defined it.
        vol.Optional("dry-run"): cv.boolean,
        vol.Optional("dry_run"): cv.boolean,
    },
    # Drop keys that no longer apply, such as preload_type, rather than
    # failing a call that used to work.
    extra=vol.REMOVE_EXTRA,
)

SCHEMA_SETLED = vol.Schema(
    {
        **_TARGET_FIELDS,
        vol.Optional("mode", default="flash"): vol.In(["off", "flash"]),
        vol.Optional("brightness", default=1): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=16)
        ),
        vol.Optional("repeats", default=2): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=256)
        ),
        # Three groups, as the pre-4.0 action had. A group with no flashes is
        # skipped, which is how it documented turning one off.
        **_led_segment_fields(1, [255, 0, 0], 0.1),
        **_led_segment_fields(2, [0, 255, 0], 0.1),
        **_led_segment_fields(3, [0, 0, 255], 0.0),
    },
    extra=vol.REMOVE_EXTRA,
)

SCHEMA_TARGET_ONLY = vol.Schema(_TARGET_FIELDS, extra=vol.REMOVE_EXTRA)


# ---------------------------------------------------------------------------
# Rendering support
# ---------------------------------------------------------------------------


class HADataProvider:
    """Supplies recorder history to odl-renderer's plot element.

    odl-renderer defines this as a protocol precisely so it need not know
    anything about Home Assistant.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Hold the Home Assistant instance."""
        self._hass = hass

    async def get_history(
        self, entity_ids: list[str], start: datetime, end: datetime
    ) -> dict[str, list[dict[str, Any]]]:
        """Return state history for *entity_ids* between *start* and *end*."""
        # Imported here because recorder is an after_dependency: it may not be
        # loaded, and only the plot element needs it.
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import get_significant_states

        raw = await get_instance(self._hass).async_add_executor_job(
            partial(
                get_significant_states,
                self._hass,
                start,
                end,
                entity_ids,
                significant_changes_only=False,
                minimal_response=True,
                no_attributes=False,
            )
        )

        result: dict[str, list[dict[str, Any]]] = {}
        for entity_id, states in raw.items():
            if not states:
                result[entity_id] = []
                continue
            # minimal_response returns the first entry as a full State object
            # and the rest as dicts, so only the first needs converting.
            first = states[0]
            result[entity_id] = [
                {"state": first.state, "last_changed": str(first.last_changed)},
                *states[1:],
            ]
        return result


def _font_search_dirs(hass: HomeAssistant, extra: str | None) -> list[str]:
    """Return font directories in priority order, skipping absent ones."""
    candidates = [
        hass.config.path("www/fonts"),
        hass.config.path("media/fonts"),
        "/media/fonts",
    ]
    if extra:
        # Semicolon-separated, as the pre-4.0 option was.
        candidates = [p.strip() for p in extra.split(";") if p.strip()] + candidates
    return [path for path in candidates if Path(path).is_dir()]


def _validate_local_paths(hass: HomeAssistant, elements: list[dict[str, Any]]) -> None:
    """Reject local paths Home Assistant has not been told to allow.

    odl-renderer opens any path beginning with a slash without checking, so
    this is load-bearing rather than a formality.
    """
    for element in elements:
        url = element.get("url")
        if (
            isinstance(url, str)
            and url.startswith("/")
            and not url.startswith("//")
            and not hass.config.is_allowed_path(url)
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="path_not_allowed",
                translation_placeholders={"path": url},
            )


# ---------------------------------------------------------------------------
# Targeting
# ---------------------------------------------------------------------------


async def _async_targets(
    hass: HomeAssistant, call: ServiceCall
) -> list[tuple[APCoordinator, str | None]]:
    """Resolve what a call targets to (coordinator, MAC) pairs.

    A MAC of None means the Access Point itself. Home Assistant expands areas
    and labels for us, which the pre-4.0 code did by hand.
    """
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    device_ids = set(call.data.get("device_id") or [])
    for entity_id in await async_extract_entity_ids(hass, call):
        if (record := entity_registry.async_get(entity_id)) and record.device_id:
            device_ids.add(record.device_id)

    targets: list[tuple[APCoordinator, str | None]] = []
    seen: set[str] = set()

    for device_id in device_ids:
        device = device_registry.async_get(device_id)
        if device is None:
            continue
        for domain, value in device.identifiers:
            if domain != DOMAIN or value in seen:
                continue
            # Identifiers are "{entry_id}_ap" or "{entry_id}_{mac}", and entry
            # ids are ULIDs, so the first underscore is the separator.
            entry_id, _, suffix = value.partition("_")
            entry = hass.config_entries.async_get_entry(entry_id)
            coordinator = getattr(entry, "runtime_data", None) if entry else None
            if not isinstance(coordinator, APCoordinator):
                continue
            seen.add(value)
            targets.append((coordinator, None if suffix == "ap" else suffix))

    if not targets:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_tags_targeted"
        )
    return targets


async def _async_target_tags(
    hass: HomeAssistant, call: ServiceCall
) -> list[tuple[APCoordinator, str]]:
    """Resolve what a call targets, rejecting anything that is not a tag."""
    tags = [
        (coordinator, mac)
        for coordinator, mac in await _async_targets(hass, call)
        if mac is not None and mac in coordinator.data
    ]
    if not tags:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_tags_targeted"
        )
    return tags


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def _async_drawcustom(call: ServiceCall) -> None:
    """Render a payload and send it to each targeted tag."""
    hass = call.hass
    elements = call.data["payload"]
    _validate_local_paths(hass, elements)

    rotate: int = call.data["rotate"]
    dry_run = call.data.get("dry-run", call.data.get("dry_run", False))

    for coordinator, mac in await _async_target_tags(hass, call):
        tag_type = coordinator.tag_type(mac)
        if tag_type is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unknown_tag_type",
                translation_placeholders={"mac": mac},
            )

        width, height = tag_type.width, tag_type.height
        # The tag applies rotation itself and fits the result to its pixel
        # grid, so matching the canvas aspect keeps that fit a no-op.
        if (int(coordinator.data[mac].rotate) * 90 + rotate) % 360 in (90, 270):
            width, height = height, width

        image = await generate_image(
            width=width,
            height=height,
            elements=elements,
            background=call.data["background"],
            accent_color=_accent_color(tag_type),
            session=async_get_clientsession(hass),
            data_provider=HADataProvider(hass),
            font_dirs=await hass.async_add_executor_job(
                _font_search_dirs,
                hass,
                coordinator.config_entry.options.get(OPT_CUSTOM_FONT_DIRS),
            ),
        )

        if dry_run:
            _LOGGER.debug("Dry run: rendered %sx%s for %s", width, height, mac)
            continue

        await coordinator.async_upload_image(
            mac,
            image,
            ttl=call.data["ttl"],
            lut=call.data["refresh_type"],
            dither_mode=call.data["dither"],
            color_scheme=_color_scheme(tag_type),
        )


def _led_pattern(data: dict[str, Any]) -> LEDPattern:
    """Build an LED pattern from a setled call."""
    if data["mode"] == "off":
        return LEDPattern.off()

    segments = [
        LEDSegment(
            color=Color(*[*data[f"color{i}"], 0, 0, 0][:3]),
            flash_speed=data[f"flash_speed{i}"],
            flash_count=data[f"flash_count{i}"],
            delay=data[f"delay{i}"],
        )
        for i in (1, 2, 3)
        # A group with no flashes is skipped, as the pre-4.0 action documented.
        if data[f"flash_count{i}"] > 0
    ]
    if not segments:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_led_segments"
        )
    return LEDPattern(
        segments=segments, repeats=data["repeats"], brightness=data["brightness"]
    )


async def _async_setled(call: ServiceCall) -> None:
    """Set a tag's LED pattern."""
    pattern = _led_pattern(call.data)
    for coordinator, mac in await _async_target_tags(call.hass, call):
        await coordinator.async_set_led(mac, pattern)


def _make_tag_command_handler(command: TagCommand):
    """Return a handler that sends *command* to every targeted tag."""

    async def handler(call: ServiceCall) -> None:
        for coordinator, mac in await _async_target_tags(call.hass, call):
            await coordinator.async_send_tag_command(mac, command)

    return handler


async def _async_reboot_ap(call: ServiceCall) -> None:
    """Reboot every targeted Access Point."""
    for coordinator, _ in await _async_targets(call.hass, call):
        await coordinator.async_reboot_ap()


async def _async_refresh_tag_types(call: ServiceCall) -> None:
    """Reload tag type definitions from the Access Point.

    Useful after it downloads a definition it did not previously hold.
    """
    for coordinator, _ in await _async_targets(call.hass, call):
        await coordinator.async_refresh_tag_types()


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""
    hass.services.async_register(
        DOMAIN, "drawcustom", _async_drawcustom, schema=SCHEMA_DRAWCUSTOM
    )
    hass.services.async_register(DOMAIN, "setled", _async_setled, schema=SCHEMA_SETLED)

    for name, command in TAG_COMMAND_SERVICES.items():
        hass.services.async_register(
            DOMAIN, name, _make_tag_command_handler(command), schema=SCHEMA_TARGET_ONLY
        )

    hass.services.async_register(
        DOMAIN, "reboot_ap", _async_reboot_ap, schema=SCHEMA_TARGET_ONLY
    )
    hass.services.async_register(
        DOMAIN,
        "refresh_tag_types",
        _async_refresh_tag_types,
        schema=SCHEMA_TARGET_ONLY,
    )
