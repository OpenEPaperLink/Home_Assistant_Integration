"""Tests for rectangle pattern rendering in ImageGen."""
import os
from io import BytesIO
import pytest
from unittest.mock import patch
from PIL import Image

from conftest import BASE_IMG_PATH, images_equal

RECTANGLE_IMG_PATH = os.path.join(BASE_IMG_PATH, 'rectangle_pattern')

@pytest.mark.asyncio
async def test_rectangle_pattern(image_gen, mock_tag_info):
    """Test rectangle pattern drawing."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "rectangle_pattern",
            "x_start": 10,
            "y_start": 10,
            "x_size": 30,
            "y_size": 30,
            "x_repeat": 5,
            "y_repeat": 3,
            "x_offset": 10,
            "y_offset": 10,
            "fill": "red",
            "outline": "black",
            "width": 1
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(RECTANGLE_IMG_PATH, 'rectangle_pattern.png'))
        assert images_equal(generated_img, example_img), "Rectangle pattern rendering failed"

@pytest.mark.asyncio
async def test_rectangle_pattern_rounded_corners(image_gen, mock_tag_info):
    """Test rounded corner rectangle pattern drawing."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "rectangle_pattern",
            "x_start": 10,
            "y_start": 10,
            "x_size": 30,
            "y_size": 30,
            "x_repeat": 3,
            "y_repeat": 2,
            "x_offset": 10,
            "y_offset": 10,
            "fill": "red",
            "outline": "black",
            "width": 1,
            "radius": 5,
            "corners": "top_left, bottom_right"
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(RECTANGLE_IMG_PATH, 'rectangle_pattern_rounded_corners.png'))
        assert images_equal(generated_img, example_img), "Rounded corner rectangle pattern rendering failed"

@pytest.mark.asyncio
async def test_rectangle_pattern(image_gen, mock_tag_info):
    """Test rounded corner rectangle pattern drawing."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "rectangle_pattern",
            "x_start": 10,
            "y_start": 10,
            "x_size": 30,
            "y_size": 30,
            "x_repeat": 0,
            "y_repeat": 0,
            "x_offset": 10,
            "y_offset": 10,
            "fill": "red",
            "outline": "black",
            "width": 1,
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(BASE_IMG_PATH, 'blank.png'))
        assert images_equal(generated_img, example_img), "Rounded corner rectangle pattern rendering failed"