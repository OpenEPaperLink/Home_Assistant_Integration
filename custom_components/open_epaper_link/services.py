"""Actions for the OpenEPaperLink integration.

The declarative renderer behind ``drawcustom`` lives in odl-renderer, which has
no Home Assistant coupling of its own. What stays here is the part that
genuinely needs Home Assistant: recorder history for plots, font locations and
path validation.

``drawcustom`` payloads are large, hand-written YAML living in people's
automations, so unlike the rest of this rewrite the action keeps accepting the
pre-4.0 call shape and coerces it. Legacy numeric values, the hyphenated
``dry-run`` key and keys that no longer apply are all handled.
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
from oepl import LUT, Color, LEDPattern, LEDSegment, TagType

from .const import DOMAIN, OPT_CUSTOM_FONT_DIRS
from .coordinator import APCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_DRAWCUSTOM = "drawcustom"
SERVICE_SETLED = "setled"


def _refresh_type(value: Any) -> LUT:
    """Accept refresh names and the pre-4.0 numeric values.

    The old numbers meant something different from what their labels implied:
    "0" was labelled Full and stored the value that forces a full waveform on
    every update. An explicit old value keeps its old meaning, but the default
    is now the adaptive mode, which refreshes cheaply and promotes to one full
    refresh nightly.
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
    if text in legacy:
        return legacy[text]
    if text in names:
        return names[text]
    raise vol.Invalid(f"Invalid refresh_type: {value}")


def _dither(value: Any) -> DitherMode:
    """Accept any epaper-dithering mode name, and the pre-4.0 numbers.

    Dithering is done here rather than on the Access Point, so the full set of
    algorithms is available instead of the three the Access Point offers. The
    old numeric values named the Access Point's own options, so they map onto
    the equivalent modes.
    """
    legacy = {"0": DitherMode.NONE, "1": DitherMode.BURKES, "2": DitherMode.ORDERED}
    text = str(value).strip().lower()
    if text in legacy:
        return legacy[text]
    try:
        return DitherMode[text.upper()]
    except KeyError:
        pass
    raise vol.Invalid(
        f"Invalid dither: {value}. Expected one of: "
        + ", ".join(mode.name.lower() for mode in DitherMode)
    )


def _color_scheme(tag_type: TagType) -> ColorScheme:
    """Return the palette to dither for, from the tag's colour table."""
    table = tag_type.color_table or {}
    has_red = "red" in table
    has_yellow = "yellow" in table
    if has_red and has_yellow:
        return ColorScheme.BWRY
    if has_red:
        return ColorScheme.BWR
    if has_yellow:
        return ColorScheme.BWY
    return ColorScheme.MONO


SCHEMA_DRAWCUSTOM = vol.Schema(
    {
        vol.Optional("entity_id", default=[]): cv.entity_ids_or_uuids,
        vol.Optional("device_id", default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("area_id", default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("label_id", default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Required("payload"): vol.All(cv.ensure_list, [dict]),
        vol.Optional("background", default="white"): cv.string,
        vol.Optional("rotate", default=0): vol.All(
            vol.Coerce(int), vol.In([0, 90, 180, 270])
        ),
        vol.Optional("dither", default="ordered"): _dither,
        vol.Optional("ttl", default=60): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional("refresh_type", default="adaptive"): _refresh_type,
        # Hyphenated, as the pre-4.0 action defined it.
        vol.Optional("dry-run", default=False): cv.boolean,
        vol.Optional("dry_run", default=False): cv.boolean,
    },
    # Silently drop keys that no longer apply, such as preload_type and
    # preload_lut, rather than failing a call that used to work.
    extra=vol.REMOVE_EXTRA,
)

SCHEMA_SETLED = vol.Schema(
    {
        vol.Optional("entity_id", default=[]): cv.entity_ids_or_uuids,
        vol.Optional("device_id", default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("area_id", default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("label_id", default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("mode", default="flash"): vol.In(["off", "flash"]),
        vol.Optional("brightness", default=2): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=16)
        ),
        vol.Optional("repeats", default=2): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=256)
        ),
        vol.Optional("color1", default=[255, 0, 0]): vol.All(
            cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min=0, max=255))]
        ),
        vol.Optional("flash_speed1", default=0.2): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=1.5)
        ),
        vol.Optional("flash_count1", default=2): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=15)
        ),
    },
    extra=vol.REMOVE_EXTRA,
)


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


def _accent_color(tag_type: TagType) -> str:
    """Return the tag's third colour, which odl-renderer draws accents in."""
    table = tag_type.color_table or {}
    return next((name for name in ("red", "yellow") if name in table), "red")


# ---------------------------------------------------------------------------
# Targeting
# ---------------------------------------------------------------------------


@callback
def _async_targeted_tags(
    hass: HomeAssistant, call: ServiceCall
) -> list[tuple[APCoordinator, str]]:
    """Resolve everything the call targets to (coordinator, MAC) pairs.

    Home Assistant expands areas and labels for us, which the pre-4.0 code did
    by hand.
    """
    entity_registry = er.async_get(hass)
    device_ids: set[str] = set(call.data.get("device_id") or [])

    for entity_id in async_extract_entity_ids(hass, call):
        if (record := entity_registry.async_get(entity_id)) and record.device_id:
            device_ids.add(record.device_id)

    device_registry = dr.async_get(hass)
    tags: list[tuple[APCoordinator, str]] = []
    seen: set[tuple[str, str]] = set()

    for device_id in device_ids:
        device = device_registry.async_get(device_id)
        if device is None:
            continue
        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is None or entry.domain != DOMAIN:
                continue
            coordinator = getattr(entry, "runtime_data", None)
            if not isinstance(coordinator, APCoordinator):
                continue
            prefix = f"{entry_id}_"
            for domain, value in device.identifiers:
                if domain != DOMAIN or not value.startswith(prefix):
                    continue
                mac = value.removeprefix(prefix)
                if mac in coordinator.data and (entry_id, mac) not in seen:
                    seen.add((entry_id, mac))
                    tags.append((coordinator, mac))

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
    dry_run: bool = call.data["dry-run"] or call.data["dry_run"]

    for coordinator, mac in _async_targeted_tags(hass, call):
        tag_type = coordinator.tag_type(mac)
        if tag_type is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unknown_tag_type",
                translation_placeholders={"mac": mac},
            )

        width, height = tag_type.width, tag_type.height
        # The tag applies rotation itself and fits the result to its pixel
        # grid, so matching the canvas aspect keeps that fit a no-op rather
        # than a rescale.
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


async def _async_setled(call: ServiceCall) -> None:
    """Flash a tag's LED."""
    if call.data["mode"] == "off":
        pattern = LEDPattern.off()
    else:
        red, green, blue = ([*call.data["color1"], 0, 0, 0])[:3]
        pattern = LEDPattern(
            segments=[
                LEDSegment(
                    color=Color(red, green, blue),
                    flash_speed=call.data["flash_speed1"],
                    flash_count=call.data["flash_count1"],
                )
            ],
            repeats=call.data["repeats"],
            brightness=call.data["brightness"],
        )

    for coordinator, mac in _async_targeted_tags(call.hass, call):
        await coordinator.async_set_led(mac, pattern)


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""
    hass.services.async_register(
        DOMAIN, SERVICE_DRAWCUSTOM, _async_drawcustom, schema=SCHEMA_DRAWCUSTOM
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SETLED, _async_setled, schema=SCHEMA_SETLED
    )
