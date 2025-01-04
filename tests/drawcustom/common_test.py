"""Tests for common cases in ImageGen."""
import os
from io import BytesIO

import pytest
from unittest.mock import patch

from PIL import Image

from homeassistant.exceptions import HomeAssistantError
from conftest import BASE_IMG_PATH, images_equal
from conftest import save_image

COMMON_IMG_PATH = os.path.join(BASE_IMG_PATH, 'common')

@pytest.mark.asyncio
async def test_multiple_elements(image_gen, mock_tag_info):
    """Test Multiple elements rendering."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [
            {'type': 'rectangle', 'x_start': 0, 'y_start': 0, 'x_end': 296, 'y_end': 128, 'fill': 'white'},
            {'type': 'text', 'x': 10, 'y': 10, 'value': 'Hello', 'size': 20, 'color': 'black'},
            {'type': 'line', 'x_start': 0, 'y_start': 40, 'x_end': 296, 'y_end': 40, 'fill': 'black', 'width': 1},
            {'type': 'circle', 'x': 148, 'y': 84, 'radius': 30, 'fill': 'red'}
        ]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(COMMON_IMG_PATH, 'multiple_elements.png'))
        assert images_equal(generated_img, example_img), "Multiple elements drawing failed"

@pytest.mark.asyncio
async def test_rotation(image_gen, mock_tag_info):
    """Test Rotated element rendering."""
    service_data = {
        "background": "white",
        "rotate": 90,
        "payload": [
            {
                'type': 'text',
                'x': 10,
                'y': 10,
                'value': 'Rotated',
                'size': 20,
                'color': 'black'
            }
        ]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(COMMON_IMG_PATH, 'rotated.png'))
        assert images_equal(generated_img, example_img), "rotated elements drawing failed"

@pytest.mark.asyncio
async def test_oversize_elements(image_gen, mock_tag_info):
    """Test Oversize element rendering."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [
            {'type': 'rectangle', 'x_start': 10, 'y_start': 0, 'x_end': 1000, 'y_end': 20, 'fill': 'red'},
            {'type': 'circle', 'x': 300, 'y': 100, 'radius': 70, 'fill': 'black'}
        ]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(COMMON_IMG_PATH, 'oversize_elements.png'))
        assert images_equal(generated_img, example_img), "Oversize elements drawing failed"

@pytest.mark.asyncio
async def test_overlapping_elements(image_gen, mock_tag_info):
    """Test Overlapping element rendering."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [
            {'type': 'rectangle', 'x_start': 0, 'y_start': 0, 'x_end': 100, 'y_end': 100, 'fill': 'red'},
            {'type': 'circle', 'x': 50, 'y': 50, 'radius': 30, 'fill': 'blue'},
            {'type': 'text', 'x': 20, 'y': 20, 'value': 'Overlapping', 'size': 20}
        ]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(COMMON_IMG_PATH, 'overlapping_elements.png'))
        assert images_equal(generated_img, example_img), "Overlapping elements drawing failed"

@pytest.mark.asyncio
async def test_negative_coordinates(image_gen, mock_tag_info):
    """Test negative coordinates rendering."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [
            {'type': 'rectangle', 'x_start': -10, 'y_start': -10, 'x_end': 50, 'y_end': 50, 'fill': 'red'},
            {'type': 'text', 'x': -20, 'y': -5, 'value': 'Negative', 'size': 20}
        ]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(COMMON_IMG_PATH, 'negative_coordinates.png'))
        assert images_equal(generated_img, example_img), "Negative coordinate elements drawing failed"
