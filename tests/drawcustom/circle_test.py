"""Tests for circle rendering in ImageGen."""
import os
from io import BytesIO
import pytest
from unittest.mock import patch
from PIL import Image

from conftest import BASE_IMG_PATH, images_equal, generate_test_image

CIRCLE_IMG_PATH = os.path.join(BASE_IMG_PATH, 'circle')

@pytest.mark.asyncio
async def test_circle_filled(image_gen, mock_tag_info):
    """Test basic circle rendering with default settings."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "circle",
            "x": 100,
            "y": 64,
            "radius": 50,
            "fill": "red",
            "outline": "black",
            "width": 2
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await generate_test_image(image_gen, service_data)

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(CIRCLE_IMG_PATH, 'circle_filled.png'))
        assert images_equal(generated_img, example_img), "Basic filled circle rendering failed"

@pytest.mark.asyncio
async def test_circle_outline(image_gen, mock_tag_info):
    """Test outline circle rendering."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "circle",
            "x": 100,
            "y": 64,
            "radius": 50,
            "outline": "red",
            "width": 3
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await generate_test_image(image_gen, service_data)

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(CIRCLE_IMG_PATH, 'circle_outline.png'))
        assert images_equal(generated_img, example_img), "Basic outline circle rendering failed"

@pytest.mark.asyncio
async def test_circle_percentage(image_gen, mock_tag_info):
    """Test basic circle rendering with percentage."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "circle",
            "x": '50%',
            "y": '50%',
            "radius": 50,
            "fill": "red",
            "outline": "black",
            "width": 2
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await generate_test_image(image_gen, service_data)

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(CIRCLE_IMG_PATH, 'circle_percentage.png'))
        assert images_equal(generated_img, example_img), "Basic filled circle rendering failed"
