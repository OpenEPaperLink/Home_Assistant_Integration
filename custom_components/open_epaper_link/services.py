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
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from io import BytesIO
from pathlib import Path
from typing import Any

import probatio as vol
from epaper_dithering import ColorScheme, DitherMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    State,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service import async_extract_entity_ids
from odl_renderer import generate_image
from oepl import LUT, Color, LEDPattern, LEDSegment, TagCommand, TagType
from PIL.Image import Image
from py_atc_ble_oepl import ATCError, FitMode
from py_atc_ble_oepl import ColorScheme as ATCColorScheme

from .atc_coordinator import ATCConfigEntry, ATCRuntimeData
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

_TARGET_FIELDS: dict[Any, Any] = {
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

    A two-colour panel has no accent, so black is the only honest answer.
    """
    return tag_type.accent_color or "black"


_RGB = vol.All(cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min=0, max=255))])
_SECONDS = vol.All(vol.Coerce(float), vol.Range(min=0, max=25.5))
_FLASH_SPEED = vol.All(vol.Coerce(float), vol.Range(min=0, max=1.5))
_FLASH_COUNT = vol.All(vol.Coerce(int), vol.Range(min=0, max=15))


def _led_segment_fields(index: int, color: list[int], delay: float) -> dict[Any, Any]:
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
        from homeassistant.components.recorder.history import get_significant_states
        from homeassistant.helpers.recorder import get_instance

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

        return {
            entity_id: [_as_history_row(row) for row in rows]
            for entity_id, rows in raw.items()
        }


def _as_history_row(row: State | dict[str, Any]) -> dict[str, Any]:
    """Normalise one recorder row into a plain mapping.

    ``minimal_response`` returns the first row of each entity as a full State
    and the rest as dicts. That is an optimisation rather than a guarantee, so
    each row is converted on its own merits instead of by position.
    """
    if isinstance(row, State):
        return {"state": row.state, "last_changed": str(row.last_changed)}
    return row


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
) -> list[tuple[ConfigEntry, str | None]]:
    """Resolve what a call targets to (entry, MAC) pairs.

    A MAC of None means the Access Point itself. Entries come back whatever
    their kind, because a tag reached over Bluetooth is as legitimate a target
    as one behind an Access Point; callers narrow on runtime_data. Home
    Assistant expands areas and labels for us, which the pre-4.0 code did by
    hand.
    """
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    device_ids = set(call.data.get("device_id") or [])
    for entity_id in await async_extract_entity_ids(call):
        if (record := entity_registry.async_get(entity_id)) and record.device_id:
            device_ids.add(record.device_id)

    targets: list[tuple[ConfigEntry, str | None]] = []
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
            if entry is None or getattr(entry, "runtime_data", None) is None:
                continue  # not loaded, so nothing to act on
            seen.add(value)
            targets.append((entry, None if suffix == "ap" else suffix))

    if not targets:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_tags_targeted"
        )
    return targets


async def _async_target_tags(
    hass: HomeAssistant, call: ServiceCall
) -> list[tuple[APCoordinator, str]]:
    """Resolve what a call targets, rejecting all but Access Point tags."""
    tags = [
        (entry.runtime_data, mac)
        for entry, mac in await _async_targets(hass, call)
        if mac is not None
        and isinstance(entry.runtime_data, APCoordinator)
        and mac in entry.runtime_data.data
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
    """Render a payload and send it to each targeted tag.

    Nothing is returned. What was drawn is on the tag's image entity, dry runs
    included, which is where it can actually be looked at -- Home Assistant
    renders an action response as JSON, so returning the image only produced a
    wall of base64 nobody could read or use.
    """
    hass = call.hass
    elements = call.data["payload"]
    _validate_local_paths(hass, elements)

    rotate: int = call.data["rotate"]
    dry_run = call.data.get("dry-run", call.data.get("dry_run", False))

    for canvas in await _async_canvases(hass, call):
        # rotate is applied here, not by the device. A quarter turn is laid
        # out on a transposed canvas and turned back below, so what is sent is
        # always the panel's own size -- which is not optional: neither the
        # Access Point nor a tag scales what it is given.
        if rotate in (90, 270):
            width, height = canvas.height, canvas.width
        else:
            width, height = canvas.width, canvas.height

        image = await generate_image(
            width=width,
            height=height,
            elements=elements,
            background=call.data["background"],
            accent_color=canvas.accent_color,
            session=async_get_clientsession(hass),
            data_provider=HADataProvider(hass),
            font_dirs=await hass.async_add_executor_job(
                _font_search_dirs, hass, canvas.options.get(OPT_CUSTOM_FONT_DIRS)
            ),
        )

        if rotate:
            # Positive is anticlockwise in PIL, matching the pre-4.0 action.
            image = image.rotate(rotate, expand=True)

        # Shown on the tag's image entity either way, so a dry run is a
        # preview rather than a silent no-op.
        canvas.preview(_to_png(image))
        if not dry_run:
            await canvas.send(image)


@dataclass(frozen=True)
class _Canvas:
    """Somewhere a drawcustom call can render to.

    An Access Point tag and a Bluetooth tag differ in where their geometry
    comes from, what colour they can accent in, where a preview goes and how a
    finished image reaches them -- and in nothing else. Building that
    difference here keeps the drawing itself a single path.
    """

    width: int
    height: int
    accent_color: str
    options: Mapping[str, Any]
    preview: Callable[[bytes], None]
    send: Callable[[Image], Awaitable[None]]


async def _async_canvases(hass: HomeAssistant, call: ServiceCall) -> list[_Canvas]:
    """Resolve what a call targets into things that can be drawn on."""
    canvases: list[_Canvas] = []
    for entry, mac in await _async_targets(hass, call):
        runtime = entry.runtime_data
        if isinstance(runtime, ATCRuntimeData):
            canvases.append(_atc_canvas(hass, entry, call))
        elif mac is not None and mac in runtime.data:
            canvases.append(_tag_canvas(runtime, mac, call))

    if not canvases:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_tags_targeted"
        )
    return canvases


def _tag_canvas(coordinator: APCoordinator, mac: str, call: ServiceCall) -> _Canvas:
    """A tag behind an Access Point, which queues the image and delivers it."""
    tag_type = coordinator.tag_type(mac)
    if tag_type is None:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="unknown_tag_type",
            translation_placeholders={"mac": mac},
        )
    return _Canvas(
        width=tag_type.width,
        height=tag_type.height,
        accent_color=_accent_color(tag_type),
        options=coordinator.config_entry.options,
        preview=partial(coordinator.async_set_preview, mac),
        send=partial(
            coordinator.async_upload_image,
            mac,
            ttl=call.data["ttl"],
            lut=call.data["refresh_type"],
            dither_mode=call.data["dither"],
            color_scheme=_color_scheme(tag_type),
        ),
    )


def _atc_canvas(
    hass: HomeAssistant, entry: ATCConfigEntry, call: ServiceCall
) -> _Canvas:
    """A tag reached directly over Bluetooth.

    Its geometry was read when the entry was set up, so nothing here has to
    talk to the tag before drawing.
    """
    runtime = entry.runtime_data
    panel = runtime.capabilities
    return _Canvas(
        width=panel.width,
        height=panel.height,
        accent_color=_atc_accent_color(panel.color_scheme),
        options=entry.options,
        preview=runtime.coordinator.async_set_rendered,
        send=partial(_async_send_to_atc, hass, entry, call.data["dither"]),
    )


def _atc_accent_color(color_scheme: int) -> str:
    """Return the colour a Bluetooth tag can accent in.

    A Bluetooth tag carries no tag type, so this comes from the colour scheme
    it reported for its own panel.
    """
    try:
        return ATCColorScheme.from_value(color_scheme).accent_color
    except ValueError:
        return "black"


async def _async_send_to_atc(
    hass: HomeAssistant, entry: ATCConfigEntry, dither_mode: DitherMode, image: Image
) -> None:
    """Hand an image to a Bluetooth tag, without waiting for it to arrive.

    Sending takes tens of seconds, which no automation should block on. A
    newer draw replaces an older still in flight rather than queueing behind
    it: the older one's picture is already stale.
    """
    runtime = entry.runtime_data
    if runtime.upload_task is not None and not runtime.upload_task.done():
        runtime.upload_task.cancel()
    runtime.upload_task = entry.async_create_background_task(
        hass, _async_upload_to_atc(entry, image, dither_mode), name=f"{DOMAIN} upload"
    )


async def _async_upload_to_atc(
    entry: ATCConfigEntry, image: Image, dither_mode: DitherMode
) -> None:
    """Send a rendered image over Bluetooth.

    Detached from the action that asked for it, so a failure is logged rather
    than raised at a caller already told the draw was accepted.
    """
    runtime = entry.runtime_data
    try:
        async with runtime.device:
            await runtime.device.upload_image(
                image, dither_mode=dither_mode, fit=FitMode.CONTAIN
            )
    except ATCError as err:
        _LOGGER.error("Could not draw on %s: %s", runtime.coordinator.address, err)


def _to_png(image: Image) -> bytes:
    """Encode a rendered image for the image entity.

    PNG rather than JPEG: these are flat-colour e-paper images, where JPEG
    ringing is both visible and larger.
    """
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


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


def _make_tag_command_handler(
    command: TagCommand,
) -> Callable[[ServiceCall], Coroutine[Any, Any, None]]:
    """Return a handler that sends *command* to every targeted tag."""

    async def handler(call: ServiceCall) -> None:
        for coordinator, mac in await _async_target_tags(call.hass, call):
            await coordinator.async_send_tag_command(mac, command)

    return handler


async def _async_target_access_points(
    hass: HomeAssistant, call: ServiceCall
) -> list[APCoordinator]:
    """Resolve what a call targets to Access Points, ignoring anything else."""
    return [
        entry.runtime_data
        for entry, _ in await _async_targets(hass, call)
        if isinstance(entry.runtime_data, APCoordinator)
    ]


async def _async_reboot_ap(call: ServiceCall) -> None:
    """Reboot every targeted Access Point."""
    for coordinator in await _async_target_access_points(call.hass, call):
        await coordinator.async_reboot_ap()


async def _async_refresh_tag_types(call: ServiceCall) -> None:
    """Reload tag type definitions from the Access Point.

    Useful after it downloads a definition it did not previously hold.
    """
    for coordinator in await _async_target_access_points(call.hass, call):
        await coordinator.async_refresh_tag_types()


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""
    hass.services.async_register(
        DOMAIN,
        "drawcustom",
        _async_drawcustom,
        schema=SCHEMA_DRAWCUSTOM,
        # Optional rather than only: existing automations call this without
        # asking for a response, and must keep working.
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
