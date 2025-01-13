"""Tests for debug grid rendering in ImageGen."""
import os
from io import BytesIO
import pytest
from unittest.mock import patch
from PIL import Image

from conftest import BASE_IMG_PATH, images_equal, save_image

DEBUG_GRID_IMG_PATH = os.path.join(BASE_IMG_PATH, 'debug_grid')


@pytest.mark.asyncio
async def test_debug_grid_basic(image_gen, mock_tag_info):
    """Test basic debug grid rendering with default settings."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "debug_grid"
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(DEBUG_GRID_IMG_PATH, 'debug_grid_basic.png'))
        assert images_equal(generated_img, example_img), "Basic debug grid rendering failed"

@pytest.mark.asyncio
async def test_debug_grid_custom_spacing(image_gen, mock_tag_info):
    """Test debug grid with custom spacing."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "debug_grid",
            "spacing": 50,
            "line_color": "black"
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(DEBUG_GRID_IMG_PATH, 'debug_grid_custom_spacing.png'))
        assert images_equal(generated_img, example_img), "Custom spacing debug grid rendering failed"

@pytest.mark.asyncio
async def test_debug_grid_solid(image_gen, mock_tag_info):
    """Test debug grid without dashed lines."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "debug_grid",
            "spacing": 25,
            "dashed": False,
            "dash_length": 10,
            "space_length": 5,
            "line_color": "r"
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(DEBUG_GRID_IMG_PATH, 'debug_grid_solid.png'))
        assert images_equal(generated_img, example_img), "Solid debug grid rendering failed"

@pytest.mark.asyncio
async def test_debug_grid_without_labels(image_gen, mock_tag_info):
    """Test debug grid without coordinate labels."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "debug_grid",
            "show_labels": False,
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(DEBUG_GRID_IMG_PATH, 'debug_grid_without_labels.png'))
        assert images_equal(generated_img, example_img), "Debug grid without labels rendering failed"