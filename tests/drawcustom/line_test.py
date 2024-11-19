"""Tests for line rendering in ImageGen."""
import os
from io import BytesIO
import pytest
from unittest.mock import patch
from PIL import Image

from conftest import BASE_IMG_PATH, images_equal, save_image

LINE_IMG_PATH = os.path.join(BASE_IMG_PATH, 'line')

@pytest.mark.asyncio
async def test_line_basic(image_gen, mock_tag_info):
    """Test basic line rendering with default settings."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "line",
            "x_start": 10,
            "y_start": 10,
            "x_end": 100,
            "y_end": 100,
            "fill": "black",
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(LINE_IMG_PATH, 'line_basic.png'))
        assert images_equal(generated_img, example_img), "Basic line rendering failed"

@pytest.mark.asyncio
async def test_line_custom(image_gen, mock_tag_info):
    """Test line drawing with custom width and color."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "line",
            "x_start": 50,
            "y_start": 20,
            "x_end": 200,
            "y_end": 100,
            "fill": "red",
            "width": 3
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(LINE_IMG_PATH, 'line_custom.png'))
        assert images_equal(generated_img, example_img), "Custom line rendering failed"