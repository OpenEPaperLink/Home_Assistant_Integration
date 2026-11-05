"""Translation consistency.

The pre-4.0 integration set config flow errors to keys that had no entry in
strings.json, so users were shown a raw key instead of a message. These tests
make that fail in CI instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

COMPONENT = Path("custom_components/open_epaper_link")
STRINGS = json.loads((COMPONENT / "strings.json").read_text())


def _flatten(node: dict, prefix: str = "") -> set[str]:
    """Return every leaf path in a nested dict."""
    paths: set[str] = set()
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            paths |= _flatten(value, path)
        else:
            paths.add(path)
    return paths


def test_en_mirrors_strings() -> None:
    """en.json must match strings.json exactly."""
    english = json.loads((COMPONENT / "translations/en.json").read_text())
    assert english == STRINGS


@pytest.mark.parametrize("lang", ["de", "pl", "pt"])
def test_translations_have_no_orphan_keys(lang: str) -> None:
    """A translated key with no counterpart in strings.json is dead weight."""
    translated = json.loads((COMPONENT / f"translations/{lang}.json").read_text())
    assert not _flatten(translated) - _flatten(STRINGS)


def test_config_flow_results_are_resolvable() -> None:
    """Every error and abort reason the flow returns must have a string."""
    source = (COMPONENT / "config_flow.py").read_text()
    defined = _flatten(STRINGS)

    for reason in re.findall(r'async_abort\(reason="([a-z_]+)"\)', source):
        assert f"config.abort.{reason}" in defined, f"missing abort: {reason}"

    for error in re.findall(r'errors\["base"\] = "([a-z_]+)"', source):
        assert f"config.error.{error}" in defined, f"missing error: {error}"

    for reason in re.findall(
        r'_abort_if_unique_id_mismatch\(reason="([a-z_]+)"\)', source
    ):
        assert f"config.abort.{reason}" in defined, f"missing abort: {reason}"


def test_raised_translation_keys_exist() -> None:
    """Every translation_key raised as an error must have a string.

    Matched via translation_domain, which entity descriptions do not carry,
    so entity translation keys are not caught by this.
    """
    defined = _flatten(STRINGS)
    pattern = re.compile(
        r"translation_domain=DOMAIN,\s*\n\s*translation_key=\"([a-z_]+)\""
    )

    for path in COMPONENT.glob("*.py"):
        for key in pattern.findall(path.read_text()):
            assert f"exceptions.{key}.message" in defined, (
                f"{path.name} raises undefined translation_key: {key}"
            )


def test_entity_translation_keys_exist() -> None:
    """Every entity translation key must resolve, or entities show raw keys."""
    defined = _flatten(STRINGS)
    pattern = re.compile(r'translation_key="([a-z_0-9]+)"')
    # Exception raises use the same keyword, so remove them first.
    exceptions = re.compile(
        r"translation_domain=DOMAIN,\s*\n\s*translation_key=\"[a-z_]+\""
    )

    platforms = {
        "sensor": ("sensor.py", "atc_sensor.py"),
        "button": ("button.py",),
        "switch": ("switch.py",),
        "select": ("select.py",),
        "text": ("text.py",),
        "image": ("image.py", "atc_image.py"),
        "event": ("event.py",),
    }
    for platform, filenames in platforms.items():
        for filename in filenames:
            path = COMPONENT / filename
            if not path.exists():
                continue
            source = exceptions.sub("", path.read_text())
            for key in pattern.findall(source):
                assert any(
                    entry.startswith(f"entity.{platform}.{key}") for entry in defined
                ), f"{filename} uses undefined entity key: {platform}.{key}"


def test_abort_reasons_used_by_helpers_exist() -> None:
    """Home Assistant's own abort reasons still need strings."""
    defined = _flatten(STRINGS)
    # _abort_if_unique_id_configured and async_update_reload_and_abort use these.
    assert "config.abort.already_configured" in defined
    assert "config.abort.reconfigure_successful" in defined


def test_every_service_has_strings() -> None:
    """Actions need a name and description, or the UI shows raw keys."""
    declared = yaml.safe_load((COMPONENT / "services.yaml").read_text())
    described = STRINGS["services"]

    assert set(declared) == set(described)
    for name, spec in described.items():
        assert spec.get("name"), f"{name} has no name"
        assert spec.get("description"), f"{name} has no description"


def test_every_service_field_has_strings() -> None:
    """Every field offered in the UI needs a label."""
    declared = yaml.safe_load((COMPONENT / "services.yaml").read_text())

    for name, spec in declared.items():
        fields = set((spec or {}).get("fields") or {})
        described = set(STRINGS["services"][name].get("fields") or {})
        assert fields <= described, (
            f"{name} is missing strings for {fields - described}"
        )
        assert described <= fields, (
            f"{name} describes unknown fields {described - fields}"
        )


def test_selector_options_are_translated() -> None:
    """A select in an action shows its raw values without these."""
    declared = yaml.safe_load((COMPONENT / "services.yaml").read_text())

    for name, spec in declared.items():
        for field, field_spec in ((spec or {}).get("fields") or {}).items():
            selector = (field_spec or {}).get("selector") or {}
            select = selector.get("select") or {}
            key = select.get("translation_key")
            if key is None:
                continue
            options = set(select.get("options") or [])
            translated = set(STRINGS["selector"][key]["options"])
            assert options == translated, (
                f"{name}.{field} options do not match selector.{key}"
            )
