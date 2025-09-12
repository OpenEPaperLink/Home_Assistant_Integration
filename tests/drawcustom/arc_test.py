"""Tests for arc rendering in ImageGen."""
import os
from io import BytesIO
import pytest
from unittest.mock import patch
from PIL import Image

from conftest import BASE_IMG_PATH, images_equal

ARC_IMG_PATH = os.path.join(BASE_IMG_PATH, 'arc')

@pytest.mark.asyncio
async def test_arc_basic(image_gen, mock_tag_info):
    """Test basic arc rendering with default settings."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "arc",
            "x": 100,
            "y": 75,
            "radius": 50,
            "start_angle": 0,
            "end_angle": 180,
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(ARC_IMG_PATH, 'arc_basic.png'))
        assert images_equal(generated_img, example_img), "Basic arc rendering failed"

@pytest.mark.asyncio
async def test_pie_slice_basic(image_gen, mock_tag_info):
    """Test basic arc rendering with default settings."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "arc",
            "x": 100,
            "y": 75,
            "radius": 50,
            "start_angle": 0,
            "end_angle": 180,
            "fill": "red",
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(ARC_IMG_PATH, 'pie_slice_basic.png'))
        assert images_equal(generated_img, example_img), "Basic pie slice rendering failed"