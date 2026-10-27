"""Action schemas, with the pre-4.0 call shapes still accepted.

drawcustom payloads are large hand-written YAML in people's automations, so
old calls must keep working. These pin the coercion.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import probatio as vol
import pytest
import yaml
from epaper_dithering import ColorScheme, DitherMode
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from oepl import LUT, LEDPattern, TagType
from PIL.Image import Image

from custom_components.open_epaper_link.const import DOMAIN
from custom_components.open_epaper_link.services import (
    SCHEMA_DRAWCUSTOM,
    SCHEMA_SETLED,
    HADataProvider,
    _as_history_row,
    _atc_accent_color,
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


@pytest.mark.parametrize(
    ("color_scheme", "expected"),
    [(0, "black"), (1, "red"), (2, "yellow"), (3, "red"), (99, "black")],
)
def test_atc_accent_color_from_the_panel(color_scheme: int, expected: str) -> None:
    """A Bluetooth tag accents in its panel's colour, and black if unknown."""
    assert _atc_accent_color(color_scheme) == expected


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

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}"), ap_config_entry.entry_id
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

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{ap_config_entry.entry_id}_ap"), ap_config_entry.entry_id
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

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}"), ap_config_entry.entry_id
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

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}"), ap_config_entry.entry_id
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

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}"), ap_config_entry.entry_id
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
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}"), ap_config_entry.entry_id
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

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}"), ap_config_entry.entry_id
    )
    await _draw(hass, device.id, dither="floyd_steinberg")

    kwargs = mock_client.upload_image.await_args.kwargs
    assert kwargs["dither_mode"] is DitherMode.FLOYD_STEINBERG
    # The fixture's tag type has no colour table beyond black and white.
    assert kwargs["color_scheme"] is ColorScheme.MONO
    assert kwargs["lut"] is LUT.DEFAULT


async def test_drawcustom_returns_nothing(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """The action draws; it does not hand anything back.

    What was drawn is on the tag's image entity, which is where it can be
    looked at -- an action response is rendered as JSON.
    """
    ap_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(ap_config_entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{ap_config_entry.entry_id}_{TAG_MAC}"), ap_config_entry.entry_id
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


# ---------------------------------------------------------------------------
# Canvas size and rotation
#
# rotate is applied here, as it was before 4.0: a quarter turn is laid out on
# a transposed canvas and rotated back, so the upload is always the panel's
# native size. It is never sent to the Access Point, which would persist it
# onto the tag's record.
#
# Native size is not optional. spr2color() in makeimage.cpp derives its output
# buffer geometry from the uploaded image, so anything else indexes outside
# the sprite. Confirmed on hardware: a transposed upload rendered as diagonal
# static on the panel.
# ---------------------------------------------------------------------------


async def _setup_tag(hass: HomeAssistant, entry) -> str:
    """Set an entry up with one tag and return that tag's device id."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{entry.entry_id}_{TAG_MAC}"), entry.entry_id
    )
    return device.id


async def _render(
    hass: HomeAssistant, device_id: str, mock_client, **extra: object
) -> Image:
    """Draw on one device and return the image that reached the tag."""
    await hass.services.async_call(
        DOMAIN,
        "drawcustom",
        {"device_id": [device_id], "payload": _text_payload(), **extra},
        blocking=True,
    )
    return mock_client.upload_image.await_args.args[0]


def test_rotate_keeps_its_old_default() -> None:
    """Existing automations relied on rotate defaulting to 0."""
    assert _drawcustom()["rotate"] == 0


@pytest.mark.parametrize("degrees", [0, 90, 180, 270])
def test_rotate_accepts_each_quarter_turn(degrees: int) -> None:
    """The four legal values pass validation."""
    assert _drawcustom(rotate=degrees)["rotate"] == degrees


def test_rotate_rejects_other_angles() -> None:
    """A tag can only rotate in quarter turns."""
    with pytest.raises(vol.Invalid):
        _drawcustom(rotate=45)


async def test_uploads_go_through_the_size_checked_handle(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """The tag handle validates size; the bare client call does not.

    Using the unchecked path is how a wrongly sized image reaches a tag and
    renders as noise instead of raising.
    """
    device_id = await _setup_tag(hass, ap_config_entry)
    await _draw(hass, device_id)

    mock_client.tag.assert_called_with(TAG_MAC)
    assert mock_client.upload_image.await_args.kwargs["fit"] == "strict"


@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
async def test_every_rotation_uploads_at_native_size(
    hass: HomeAssistant, ap_config_entry, mock_client, rotate: int
) -> None:
    """Whatever the rotation, what reaches the tag matches the panel.

    A quarter turn draws on a transposed canvas, so this only holds because
    the image is rotated back before upload.
    """
    device_id = await _setup_tag(hass, ap_config_entry)
    uploaded = await _render(hass, device_id, mock_client, rotate=rotate)

    # The fixture's tag type is 296x128.
    assert uploaded.size == (296, 128)


async def test_a_quarter_turn_rotates_the_content(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """The rotation must actually be applied, not just sized away.

    A rectangle in the top-left corner lands in a different corner once
    turned, which a no-op rotation would not do.
    """
    device_id = await _setup_tag(hass, ap_config_entry)
    await _draw(hass, device_id, rotate=0)
    upright = mock_client.upload_image.await_args.args[0].convert("L")
    await _draw(hass, device_id, rotate=90)
    turned = mock_client.upload_image.await_args.args[0].convert("L")

    assert upright.tobytes() != turned.tobytes()


async def test_rotation_is_never_sent_to_the_access_point(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """The Access Point persists rotate onto the tag's stored record.

    Sending it per draw would rewrite the tag's own configuration, which the
    pre-4.0 action never did.
    """
    device_id = await _setup_tag(hass, ap_config_entry)
    await _draw(hass, device_id, rotate=270)

    assert "rotate" not in mock_client.upload_image.await_args.kwargs


async def test_stored_rotation_does_not_change_the_canvas(
    hass: HomeAssistant, ap_config_entry, mock_client
) -> None:
    """A tag configured sideways still gets a native-size image.

    The Access Point applies that setting itself when building the tag's
    buffer, so accounting for it here would double it.
    """
    mock_client.set_tags(make_tag(TAG_MAC, rotate=1))
    device_id = await _setup_tag(hass, ap_config_entry)
    uploaded = await _render(hass, device_id, mock_client)

    assert uploaded.size == (296, 128)


# ---------------------------------------------------------------------------
# Recorder history, which feeds odl-renderer's plot element
# ---------------------------------------------------------------------------


def test_history_row_from_a_state_object() -> None:
    """A State is flattened to the mapping the renderer expects."""
    moment = dt_util.utcnow()
    row = _as_history_row(State("sensor.x", "21.5", last_changed=moment))

    assert row == {"state": "21.5", "last_changed": str(moment)}


def test_history_row_from_a_dict_is_passed_through() -> None:
    """Rows the recorder already returned as dicts are left alone."""
    row = {"state": "20.0", "last_changed": "2026-01-01T00:00:00+00:00"}

    assert _as_history_row(row) is row


async def test_every_history_row_is_normalised(hass: HomeAssistant) -> None:
    """Not just the first one.

    minimal_response returns the first row of each entity as a State and the
    rest as dicts, but that is an optimisation rather than a guarantee. Trusting
    the position would leave a State in the output the moment it changed, and
    the renderer would fail on an attribute it cannot read.
    """
    moment = dt_util.utcnow()
    rows = [
        State("sensor.x", "1", last_changed=moment),
        {"state": "2", "last_changed": "later"},
        State("sensor.x", "3", last_changed=moment),
    ]

    instance = MagicMock()
    instance.async_add_executor_job = AsyncMock(
        # Run the job, so the patched recorder call is what supplies the rows.
        side_effect=lambda job: job()
    )
    with (
        patch("homeassistant.helpers.recorder.get_instance", return_value=instance),
        patch(
            "homeassistant.components.recorder.history.get_significant_states",
            return_value={"sensor.x": rows},
        ),
    ):
        history = await HADataProvider(hass).get_history(
            ["sensor.x"], moment, dt_util.utcnow()
        )

    assert history["sensor.x"] == [
        {"state": "1", "last_changed": str(moment)},
        {"state": "2", "last_changed": "later"},
        {"state": "3", "last_changed": str(moment)},
    ]


async def test_history_of_an_entity_with_no_rows(hass: HomeAssistant) -> None:
    """An entity the recorder knows nothing about yields an empty list."""
    instance = MagicMock()
    instance.async_add_executor_job = AsyncMock(side_effect=lambda job: job())
    with (
        patch("homeassistant.helpers.recorder.get_instance", return_value=instance),
        patch(
            "homeassistant.components.recorder.history.get_significant_states",
            return_value={"sensor.x": []},
        ),
    ):
        history = await HADataProvider(hass).get_history(
            ["sensor.x"], dt_util.utcnow(), dt_util.utcnow()
        )

    assert history == {"sensor.x": []}
