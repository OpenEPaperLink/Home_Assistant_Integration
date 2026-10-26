"""Image entity for a tag running ATC firmware."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .atc_coordinator import ATCCoordinator
from .entity import ATCEntity

ATC_IMAGE = ImageEntityDescription(key="content", translation_key="content")


class ATCImage(ATCEntity, ImageEntity):
    """Shows what was last drawn on the tag.

    Unlike an Access Point, which serves the tag's current framebuffer, an ATC
    tag cannot be read back over Bluetooth. The only picture available is the
    one this integration last sent, so nothing is shown until something is.
    """

    _attr_content_type = "image/png"

    def __init__(
        self, hass: HomeAssistant, coordinator: ATCCoordinator, entry_id: str
    ) -> None:
        """Set up the entity."""
        super().__init__(coordinator, entry_id, ATC_IMAGE)
        ImageEntity.__init__(self, hass)
        self._shown = coordinator.rendered
        self._attr_image_last_updated = dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Timestamp a newly drawn image so the frontend refetches it.

        Every advertisement also updates the coordinator, so this checks that
        the image is a new one rather than timestamping it again on each.
        """
        if self.coordinator.rendered is not self._shown:
            self._shown = self.coordinator.rendered
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Return the last image drawn on this tag."""
        return self.coordinator.rendered
