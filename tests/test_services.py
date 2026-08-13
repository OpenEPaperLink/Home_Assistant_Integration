"""Action schemas, with the pre-4.0 call shapes still accepted.

drawcustom payloads are large hand-written YAML in people's automations, so
old calls must keep working. These pin the coercion.
"""

from __future__ import annotations

import json
from base64 import b64decode
from pathlib import Path

import pytest
import voluptuous as vol
import yaml
from epaper_dithering import ColorScheme, DitherMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from oepl import LUT, LEDPattern, Rotation, TagType

from custom_components.open_epaper_link.const import DOMAIN
from custom_components.open_epaper_link.services import (
    SCHEMA_DRAWCUSTOM,
    SCHEMA_SETLED,
    _color_scheme,
    _led_pattern,
    async_register_services,
)

from .conftest import TAG_MAC, make_tag

PAYLOAD = [{"type": "text", "value": "Hello", "x": 0, "y": 0}]


def _drawcustom(**overrides: object) -> dict:
    """Validate a drawcustom call, as Home Assistant would."""
    return SCHEMA_DRAWCUSTOM({"payload": PAYLOAD, **overrides})


# ---------------------------------------------------------------------------
# refresh_type
# ---------------------------------------------------------------------------


def test_refresh_type_defaults_to_adaptive() -> None:
    """The default no longer forces a full refresh on every update.

    The pre-4.0 default was "0", labelled Full, which stored the value that
    makes the tag do a full waveform every time and drains its battery.
    """
    assert _drawcustom()["refresh_type"] is LUT.DEFAULT


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [
        ("0", LUT.NO_REPEAT),  # was labelled "Full"
        ("1", LUT.FAST),
        ("2", LUT.FAST_NO_REDS),
        ("3", LUT.DEFAULT),
    ],
)
def test_legacy_refresh_type_values_keep_their_meaning(
    legacy: str, expected: LUT
) -> None:
    """An explicit old value must still do what it used to."""
    assert _drawcustom(refresh_type=legacy)["refresh_type"] is expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("adaptive", LUT.DEFAULT),
        ("full", LUT.NO_REPEAT),
        ("fast", LUT.FAST),
        ("fast_no_red", LUT.FAST_NO_REDS),
    ],
)
def test_refresh_type_names(name: str, expected: LUT) -> None:
    """The new names are self-describing."""
    assert _drawcustom(refresh_type=name)["refresh_type"] is expected


def test_refresh_type_rejects_nonsense() -> None:
    """An unrecognised value fails validation rather than silently defaulting."""
    with pytest.raises(vol.Invalid):
        _drawcustom(refresh_type="turbo")


# ---------------------------------------------------------------------------
# dither
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [
        ("0", DitherMode.NONE),
        ("1", DitherMode.BURKES),
        ("2", DitherMode.ORDERED),
        (2, DitherMode.ORDERED),
    ],
)
def test_legacy_dither_values(legacy: object, expected: DitherMode) -> None:
    """The old numbers named the Access Point's three options."""
    assert _drawcustom(dither=legacy)["dither"] is expected


def test_dither_accepts_every_library_mode() -> None:
    """Dithering happens here now, so the full algorithm set is available."""
    for mode in DitherMode:
        assert _drawcustom(dither=mode.name.lower())["dither"] is mode


def test_dither_rejects_nonsense() -> None:
    """An unknown algorithm fails rather than silently falling back."""
    with pytest.raises(vol.Invalid):
        _drawcustom(dither="sparkly")


# ---------------------------------------------------------------------------
# Other legacy call shapes
# ---------------------------------------------------------------------------


def test_hyphenated_dry_run_is_accepted() -> None:
    """The pre-4.0 action spelled it with a hyphen."""
    assert _drawcustom(**{"dry-run": True})["dry-run"] is True


def test_obsolete_keys_are_dropped_not_rejected() -> None:
    """A call carrying keys that no longer apply must still work."""
    validated = _drawcustom(preload_type=1, preload_lut=2, some_future_key="x")
    assert "preload_type" not in validated
    assert validated["payload"] == PAYLOAD


def test_ttl_keeps_its_old_default() -> None:
    """Existing automations relied on the 60 second default."""
    assert _drawcustom()["ttl"] == 60


def test_payload_is_required() -> None:
    """There is nothing to draw without one."""
    with pytest.raises(vol.Invalid):
        SCHEMA_DRAWCUSTOM({"background": "white"})


# ---------------------------------------------------------------------------
# Colour scheme
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("colors", "expected"),
    [
        (["white", "black"], ColorScheme.MONO),
        (["white", "black", "red"], ColorScheme.BWR),
        (["white", "black", "yellow"], ColorScheme.BWY),
        (["white", "black", "red", "yellow"], ColorScheme.BWRY),
    ],
)
def test_color_scheme_from_the_tag_type(
    colors: list[str], expected: ColorScheme
) -> None:
    """Dithering targets the palette the tag can actually render."""
    tag_type = TagType.from_dict(
        0x01,
        {
            "width": 296,
            "height": 128,
            "colortable": {name: [0, 0, 0] for name in colors},
        },
    )
    assert _color_scheme(tag_type) is expected


# ---------------------------------------------------------------------------
# setled, which has three colour groups
# ---------------------------------------------------------------------------


def _setled(**overrides: object) -> dict:
    """Validate a setled call, as Home Assistant would."""
    return SCHEMA_SETLED(dict(overrides))


def test_all_three_led_groups_survive() -> None:
    """A three-colour call must not lose groups two and three.

    They were silently dropped at one point, which is worse than failing.
    """
    pattern = _led_pattern(
        _setled(
            color1=[255, 0, 0],
            color2=[0, 255, 0],
            color3=[0, 0, 255],
        )
    )
    assert len(pattern.segments) == 3
    assert [(s.color.r, s.color.g, s.color.b) for s in pattern.segments] == [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
    ]


def test_a_group_with_no_flashes_is_skipped() -> None:
    """That is how the pre-4.0 action documented turning a group off."""
    pattern = _led_pattern(_setled(flash_count2=0, flash_count3=0))
    assert len(pattern.segments) == 1


def test_setled_off_mode() -> None:
    """Off stops the pattern rather than flashing anything."""
    assert _led_pattern(_setled(mode="off")).encode() == LEDPattern.off().encode()


def test_setled_rejects_an_empty_pattern() -> None:
    """Silently sending nothing would look like the action failed."""
    with pytest.raises(ServiceValidationError):
        _led_pattern(_setled(flash_count1=0, flash_count2=0, flash_count3=0))


def test_led_delays_are_carried_through() -> None:
    """Delay between groups is part of the pattern, not decoration."""
    pattern = _led_pattern(_setled(delay1=1.5))
    assert pattern.segments[0].delay == 1.5


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def test_every_declared_service_is_registered(hass: HomeAssistant) -> None:
    """services.yaml and the registered actions must not drift apart.

    They did: the file declared eight actions while only two were registered,
    so six of them appeared in the UI and failed when called.
    """
    async_register_services(hass)
    await hass.async_block_till_done()

    declared = yaml.safe_load(
        (Path("custom_components/open_epaper_link/services.yaml")).read_text()
    )
    registered = set(hass.services.async_services_for_domain(DOMAIN))
    assert set(declared) == registered


# ---------------------------------------------------------------------------
# Targeting
# ---------------------------------------------------------------------------


async def test_targeting_a_tag_device(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """Actions target tags as devices, which is how a tag is picked in the UI.

    Restricting the target to entities would make you choose one of a tag's
    sensors to redraw the whole display.
    """
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}")}
    )
    assert device is not None

    await hass.services.async_call(
        DOMAIN, "clear_pending", {"device_id": [device.id]}, blocking=True
    )

    mock_client.send_tag_cmd.assert_awaited_once()
    assert mock_client.send_tag_cmd.await_args.args[0] == TAG_MAC


async def test_targeting_an_entity_resolves_to_its_tag(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """Targeting an entity still works, and resolves to the tag behind it."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}_temperature"
    )

    await hass.services.async_call(
        DOMAIN, "force_refresh", {"entity_id": [entity_id]}, blocking=True
    )

    mock_client.send_tag_cmd.assert_awaited_once()
    assert mock_client.send_tag_cmd.await_args.args[0] == TAG_MAC


async def test_targeting_the_access_point_device(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """Access Point actions target the Access Point's own device."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{ap_config_entry.entry_id}_ap")}
    )

    await hass.services.async_call(
        DOMAIN, "reboot_ap", {"device_id": [device.id]}, blocking=True
    )

    mock_client.reboot_ap.assert_awaited_once()


async def test_targeting_nothing_is_an_error(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """A call that resolves to no tags should say so, not silently do nothing."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "clear_pending", {"device_id": ["nonexistent"]}, blocking=True
        )


# ---------------------------------------------------------------------------
# drawcustom against a real entry
# ---------------------------------------------------------------------------


def _text_payload() -> list[dict]:
    """A payload simple enough to render without fonts or network access."""
    return [{"type": "rectangle", "x_start": 0, "y_start": 0, "x_end": 10, "y_end": 10}]


async def _draw(hass: HomeAssistant, device_id: str, **extra: object) -> None:
    """Call drawcustom against one device."""
    await hass.services.async_call(
        DOMAIN,
        "drawcustom",
        {"device_id": [device_id], "payload": _text_payload(), **extra},
        blocking=True,
    )


async def test_dry_run_renders_without_uploading(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """A dry run must not send anything to the tag."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}")}
    )
    await _draw(hass, device.id, **{"dry-run": True})

    mock_client.upload_image.assert_not_awaited()


async def test_dry_run_shows_the_result_on_the_image_entity(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """Otherwise a dry run would be indistinguishable from doing nothing."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = ap_config_entry.runtime_data
    assert coordinator.preview(TAG_MAC) is None

    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}")}
    )
    await _draw(hass, device.id, **{"dry-run": True})

    preview = coordinator.preview(TAG_MAC)
    assert preview is not None
    assert preview.startswith(b"\x89PNG")


async def test_a_real_call_uploads_and_previews(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """A normal call both sends the image and shows it immediately.

    The tag takes a while to check in and render, so without the preview the
    entity would show the previous picture until it did.
    """
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}")}
    )
    await _draw(hass, device.id)

    mock_client.upload_image.assert_awaited_once()
    assert ap_config_entry.runtime_data.preview(TAG_MAC) is not None


async def test_preview_is_dropped_once_the_tag_renders(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """The tag's own picture wins as soon as it reports a new image hash."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = ap_config_entry.runtime_data
    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}")}
    )
    await _draw(hass, device.id, **{"dry-run": True})
    assert coordinator.preview(TAG_MAC) is not None

    coordinator._handle_tag_update(make_tag(TAG_MAC, hash="a-different-hash"))
    await hass.async_block_till_done()

    assert coordinator.preview(TAG_MAC) is None


async def test_upload_uses_the_tags_own_palette(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """Dithering targets what the tag can render, not a fixed assumption."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}")}
    )
    await _draw(hass, device.id, dither="floyd_steinberg")

    kwargs = mock_client.upload_image.await_args.kwargs
    assert kwargs["dither_mode"] is DitherMode.FLOYD_STEINBERG
    # The fixture's tag type has no colour table beyond black and white.
    assert kwargs["color_scheme"] is ColorScheme.MONO
    assert kwargs["lut"] is LUT.DEFAULT


async def test_drawcustom_returns_the_rendered_image(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """A script can reuse what was drawn, rather than only sending it."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}")}
    )
    response = await hass.services.async_call(
        DOMAIN,
        "drawcustom",
        {"device_id": [device.id], "payload": _text_payload()},
        blocking=True,
        return_response=True,
    )

    [rendered] = response["images"]
    assert rendered["mac"] == TAG_MAC
    assert rendered["mime_type"] == "image/png"
    # The fixture's tag type is 296x128 and unrotated.
    assert (rendered["width"], rendered["height"]) == (296, 128)
    assert b64decode(rendered["image_base64"]).startswith(b"\x89PNG")


async def test_response_survives_being_json(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """Service responses cross a JSON boundary, so raw bytes would not do."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}")}
    )
    response = await hass.services.async_call(
        DOMAIN,
        "drawcustom",
        {"device_id": [device.id], "payload": _text_payload()},
        blocking=True,
        return_response=True,
    )

    json.dumps(response)


async def test_calls_without_return_response_still_work(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """Existing automations do not ask for a response and must keep working."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}")}
    )
    assert (
        await hass.services.async_call(
            DOMAIN,
            "drawcustom",
            {"device_id": [device.id], "payload": _text_payload()},
            blocking=True,
        )
        is None
    )


async def test_dry_run_still_returns_the_image(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """Rendering without sending is exactly when the result is most useful."""
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}")}
    )
    response = await hass.services.async_call(
        DOMAIN,
        "drawcustom",
        {"device_id": [device.id], "payload": _text_payload(), "dry-run": True},
        blocking=True,
        return_response=True,
    )

    assert len(response["images"]) == 1
    mock_client.upload_image.assert_not_awaited()


# ---------------------------------------------------------------------------
# rotation
#
# The Access Point stores what it is sent: web.cpp assigns the uploaded value
# to taginfo->rotate, which contentmanager.cpp reads back as
# imageParams.rotate. Rotation therefore replaces the tag's setting rather
# than adding to it, and an unset field must not be sent at all.
# ---------------------------------------------------------------------------


async def _setup_tag(hass: HomeAssistant, entry, **tag_overrides: object) -> str:
    """Set an entry up with one tag and return that tag's device id."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{entry.entry_id}_{TAG_MAC}")}
    )
    return device.id


def test_rotate_has_no_default() -> None:
    """An unset rotate must stay unset, not become 0.

    A 0 default would be indistinguishable from the caller asking for no
    rotation, and would reset the tag's stored setting on every call.
    """
    assert "rotate" not in _drawcustom()


@pytest.mark.parametrize("degrees", [0, 90, 180, 270])
def test_rotate_accepts_each_quarter_turn(degrees: int) -> None:
    """The four legal values pass validation."""
    assert _drawcustom(rotate=degrees)["rotate"] == degrees


def test_rotate_rejects_other_angles() -> None:
    """A tag can only rotate in quarter turns."""
    with pytest.raises(vol.Invalid):
        _drawcustom(rotate=45)


async def test_unset_rotate_is_not_sent(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """Omitting rotate leaves the tag's configured rotation alone."""
    device_id = await _setup_tag(hass, ap_config_entry)
    await _draw(hass, device_id)

    assert mock_client.upload_image.await_args.kwargs["rotate"] is None


async def test_rotate_is_forwarded_as_a_quarter_turn(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """Degrees are converted to the wire's quarter-turn count."""
    device_id = await _setup_tag(hass, ap_config_entry)
    await _draw(hass, device_id, rotate=270)

    assert mock_client.upload_image.await_args.kwargs["rotate"] is Rotation.R270


async def test_rotate_transposes_the_canvas(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """A quarter turn swaps the canvas, so the tag's fit stays a no-op."""
    device_id = await _setup_tag(hass, ap_config_entry)
    response = await hass.services.async_call(
        DOMAIN,
        "drawcustom",
        {"device_id": [device_id], "payload": _text_payload(), "rotate": 90},
        blocking=True,
        return_response=True,
    )

    [rendered] = response["images"]
    assert (rendered["width"], rendered["height"]) == (128, 296)


async def test_half_turn_does_not_transpose(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """180 degrees keeps the aspect, so the canvas must not swap."""
    device_id = await _setup_tag(hass, ap_config_entry)
    response = await hass.services.async_call(
        DOMAIN,
        "drawcustom",
        {"device_id": [device_id], "payload": _text_payload(), "rotate": 180},
        blocking=True,
        return_response=True,
    )

    [rendered] = response["images"]
    assert (rendered["width"], rendered["height"]) == (296, 128)


async def test_stored_rotation_transposes_when_rotate_is_unset(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """A tag already configured sideways still gets a matching canvas."""
    mock_client.set_tags(make_tag(TAG_MAC, rotate=1))
    device_id = await _setup_tag(hass, ap_config_entry)
    response = await hass.services.async_call(
        DOMAIN,
        "drawcustom",
        {"device_id": [device_id], "payload": _text_payload()},
        blocking=True,
        return_response=True,
    )

    [rendered] = response["images"]
    assert (rendered["width"], rendered["height"]) == (128, 296)


async def test_rotation_replaces_rather_than_accumulates(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """The regression this suite exists for.

    A tag stored at 90 degrees, asked to draw at 180, must render at 180 --
    not at 270. Adding the two would both transpose the canvas wrongly and
    send the wrong quarter turn.
    """
    mock_client.set_tags(make_tag(TAG_MAC, rotate=1))
    device_id = await _setup_tag(hass, ap_config_entry)
    response = await hass.services.async_call(
        DOMAIN,
        "drawcustom",
        {"device_id": [device_id], "payload": _text_payload(), "rotate": 180},
        blocking=True,
        return_response=True,
    )

    [rendered] = response["images"]
    assert (rendered["width"], rendered["height"]) == (296, 128)
    assert mock_client.upload_image.await_args.kwargs["rotate"] is Rotation.R180
