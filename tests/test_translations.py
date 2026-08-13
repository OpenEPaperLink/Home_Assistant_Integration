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
