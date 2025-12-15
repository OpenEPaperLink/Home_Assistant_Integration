from __future__ import annotations

import base64
import io
import logging
import os
import urllib

import requests
import qrcode
from PIL import Image
from resizeimage import resizeimage
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.network import get_url

from ..const import DOMAIN
from .registry import element_handler
from .types import ElementType, DrawingContext

_LOGGER = logging.getLogger(__name__)


@element_handler(ElementType.QRCODE, requires=["x", "y", "data"])
async def draw_qrcode(ctx: DrawingContext, element: dict) -> None:
    """Draw QR code element.

    Generates and renders a QR code with the specified data and properties.

    Args:
        ctx: Drawing context
        element: Element dictionary with QR code properties
    Raises:
        HomeAssistantError: If QR code generation fails
    """

    # Coordinates
    x = ctx.coords.parse_x(element['x'])
    y = ctx.coords.parse_y(element['y'])

    # Get QR code properties
    color = ctx.colors.resolve(element.get('color', "black"))
    bgcolor = ctx.colors.resolve(element.get('bgcolor', "white"))
    border = element.get('border', 1)
    boxsize = element.get('boxsize', 2)

    try:
        # Create QR code instance
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=boxsize,
            border=border,
        )

        # Add data and generate QR code
        qr.add_data(element['data'])
        qr.make(fit=True)

        # Create QR code image
        qr_img = qr.make_image(fill_color=color[:3], back_color=bgcolor[:3])  # Convert RGBA to RGB
        qr_img = qr_img.convert("RGBA")

        # Calculate position
        position = (x, y)

        # Paste QR code onto main image
        ctx.img.paste(qr_img, position, qr_img)

        # Return bottom position
        ctx.pos_y = y + qr_img.height

    except Exception as e:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="qr_generation_failed",
            translation_placeholders={ "error": str(e)}
        )


@element_handler(ElementType.DLIMG, requires=["x", "y", "url", "xsize", "ysize"])
async def draw_downloaded_image(ctx: DrawingContext, element: dict) -> None:
    """
    Draw downloaded or local image.

    Downloads and renders an image from a URL, or loads and renders
    an image from a local path or data URI.

    Args:
        ctx: Drawing context
        element: Element dictionary with image properties
    Raises:
        HomeAssistantError: If image loading or processing fails
    """
    try:
        # Get image properties
        pos_x = element['x']
        pos_y = element['y']
        target_size = (element['xsize'], element['ysize'])
        rotate = element.get('rotate', 0)
        resize_method = element.get('resize_method', 'stretch')

        # Check if URL is an image entity
        if element['url'].startswith('image.') or element['url'].startswith('camera.'):
            # Get state of the image entity
            state = ctx.hass.states.get(element['url'])
            if not state:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="image_entity_not_found",
                    translation_placeholders={"entity_id": element['url']}
                )

            # Get image URL from entity attributes
            image_url = state.attributes.get("entity_picture")
            if not image_url:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="image_entity_no_url",
                    translation_placeholders={"entity_id": element['url']}
                )

            # If the URL is relative, make it absolute using HA's base URL
            if image_url.startswith("/"):
                base_url = get_url(ctx.hass)
                image_url = f"{base_url}{image_url}"

            # Update URL to the actual image URL
            element['url'] = image_url

        # Load image based on URL type
        if element['url'].startswith(('http://', 'https://')):
            # Download web image
            response = await ctx.hass.async_add_executor_job(
                requests.get, element['url'])
            if response.status_code != 200:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="image_download_failed",
                    translation_placeholders={ "status_code": response.status_code}
                )
            source_img = Image.open(io.BytesIO(response.content))

        elif element['url'].startswith('data:'):
            # Handle data URI
            try:
                header, encoded = element['url'].split(',', 1)
                if ';base64' in header:
                    decoded = base64.b64decode(encoded)
                else:
                    decoded = urllib.parse.unquote_to_bytes(encoded)
                source_img = Image.open(io.BytesIO(decoded))
            except Exception as e:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="image_data_uri_invalid",
                    translation_placeholders={ "error": str(e)}
                )

        else:
            # Handle local file
            if not element['url'].startswith('/'):
                media_path = ctx.hass.config.path('media')
                full_path = os.path.join(media_path, element['url'])
            else:
                full_path = element['url']
            source_img = await ctx.hass.async_add_executor_job(Image.open, full_path)

        # Process image
        if rotate:
            source_img = source_img.rotate(-rotate, expand=True)

        # Resize if needed
        if source_img.size != target_size:
            if resize_method in ['crop', 'cover', 'contain']:
                source_img = resizeimage.resize(resize_method, source_img, target_size)
            elif resize_method != 'stretch':
                _LOGGER.warning(f"Warning: resize_method is set to unsupported method '{resize_method}', this will result in simple stretch resizing")

            if source_img.size != target_size:
                source_img = source_img.resize(target_size)

        # Convert to RGBA
        source_img = source_img.convert("RGBA")

        # Create temporary image for composition
        temp_img = Image.new("RGBA", ctx.img.size)
        temp_img.paste(source_img, (pos_x, pos_y), source_img)

        # Composite images
        img_composite = Image.alpha_composite(ctx.img, temp_img)
        ctx.img.paste(img_composite, (0, 0))

        ctx.pos_y = pos_y + target_size[1]

    except Exception as e:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="image_process_failed",
            translation_placeholders={ "error": str(e)}
        )