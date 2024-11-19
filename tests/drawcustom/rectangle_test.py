"""Tests for rectangle rendering in ImageGen."""
import os
from io import BytesIO
import pytest
from unittest.mock import patch
from PIL import Image

from conftest import BASE_IMG_PATH, images_equal, save_image

RECTANGLE_IMG_PATH = os.path.join(BASE_IMG_PATH, 'rectangle')

@pytest.mark.asyncio
async def test_rectangle_filled(image_gen, mock_tag_info):
    """Test filled rectangle drawing."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "rectangle",
            "x_start": 50,
            "y_start": 20,
            "x_end": 200,
            "y_end": 100,
            "fill": "red",
            "outline": "black",
            "width": 2
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(RECTANGLE_IMG_PATH, 'rectangle_filled.png'))
        assert images_equal(generated_img, example_img), "Filled rectangle rendering failed"

@pytest.mark.asyncio
async def test_rectangle_outline(image_gen, mock_tag_info):
    """Test outlined rectangle drawing."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "rectangle",
            "x_start": 50,
            "y_start": 20,
            "x_end": 200,
            "y_end": 100,
            "outline": "red",
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
        example_img = Image.open(os.path.join(RECTANGLE_IMG_PATH, 'rectangle_outline.png'))
        assert images_equal(generated_img, example_img), "Outlined rectangle rendering failed"

@pytest.mark.asyncio
async def test_rectangle_rounded_corners(image_gen, mock_tag_info):
    """Test rounded corner rectangle drawing."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "rectangle",
            "x_start": 50,
            "y_start": 20,
            "x_end": 200,
            "y_end": 100,
            "fill": "red",
            "outline": "black",
            "width": 2,
            "radius": 15,
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
        example_img = Image.open(os.path.join(RECTANGLE_IMG_PATH, 'rectangle_rounded_corners.png'))
        assert images_equal(generated_img, example_img), "Rounded corner rectangle rendering failed"