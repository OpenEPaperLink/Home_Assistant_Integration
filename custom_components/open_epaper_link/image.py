"""Shows what is currently displayed on each tag."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util
from oepl import OEPLError

from .coordinator import APConfigEntry, APCoordinator
from .entity import OpenEPaperLinkTagEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001  (signature fixed by Home Assistant)
    entry: APConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up an image entity per tag."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _async_add_new_tags() -> None:
        """Create an image entity for newly seen tags."""
        if new := set(coordinator.data) - known:
            known.update(new)
            async_add_entities(TagImage(coordinator, mac) for mac in new)

    _async_add_new_tags()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_tags))


class TagImage(OpenEPaperLinkTagEntity, ImageEntity):
    """The image currently rendered on a tag.

    Fetched lazily and cached until the tag reports a different image hash, so
    a dashboard showing several tags does not re-pull unchanged images.
    """

    def __init__(self, coordinator: APCoordinator, mac: str) -> None:
        """Set up the entity."""
        super().__init__(coordinator, mac, "content")
        ImageEntity.__init__(self, coordinator.hass)
        self._cached: bytes | None = None
        self._cached_hash: str | None = None
        self._attr_image_last_updated = dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Invalidate the cache when the tag renders something new."""
        tag = self.tag
        if tag is not None and tag.hash != self._cached_hash:
            self._cached = None
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Return the current image, decoding it if it has changed."""
        tag = self.tag
        if tag is None:
            return None
        if self._cached is not None and self._cached_hash == tag.hash:
            return self._cached

        try:
            image = await self.coordinator.client.get_image(self._mac)
        except (OEPLError, ValueError) as err:
            # ValueError means the Access Point has no tag type for this
            # hardware, so the raw bitmap cannot be interpreted.
            self.coordinator.logger.debug(
                "Could not fetch image for %s: %s", self._mac, err
            )
            return None

        if image is None:
            return None

        self._cached = _to_png(image)
        self._cached_hash = tag.hash
        return self._cached


def _to_png(image: object) -> bytes:
    """Encode a decoded image as PNG.

    PNG rather than JPEG: these are flat-colour e-paper images, where JPEG
    ringing is both visible and larger.
    """
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")  # type: ignore[attr-defined]
    return buffer.getvalue()
