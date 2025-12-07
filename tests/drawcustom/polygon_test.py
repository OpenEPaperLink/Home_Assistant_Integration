"""Tests for polygon rendering in ImageGen."""
import os
from io import BytesIO
import pytest
from unittest.mock import patch
from PIL import Image

from conftest import BASE_IMG_PATH, images_equal, generate_test_image

POLYGON_IMG_PATH = os.path.join(BASE_IMG_PATH, 'polygon')

@pytest.mark.asyncio
async def test_polygon_basic(image_gen, mock_tag_info):
    """Test basic polygon rendering with default settings."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "polygon",
            "points": [[10, 10], [50, 10], [50, 50], [10, 50]],
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await generate_test_image(image_gen, service_data)

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(POLYGON_IMG_PATH, 'polygon_basic.png'))
        assert images_equal(generated_img, example_img), "Basic polygon rendering failed"

@pytest.mark.asyncio
async def test_polygon_filled(image_gen, mock_tag_info):
    """Test filled polygon rendering with default settings."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "polygon",
            "points": [[10, 10], [50, 10], [50, 50], [10, 70]],
            "fill": "hr"
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await generate_test_image(image_gen, service_data)
        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(POLYGON_IMG_PATH, 'polygon_filled.png'))
        assert images_equal(generated_img, example_img), "Filled polygon rendering failed"