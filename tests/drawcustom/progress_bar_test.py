"""Tests for progress bar rendering in ImageGen."""
import os
from io import BytesIO
import pytest
from unittest.mock import patch
from PIL import Image

from conftest import BASE_IMG_PATH, images_equal
from conftest import save_image

QR_CODE_IMG_PATH = os.path.join(BASE_IMG_PATH, 'progress_bar')

@pytest.mark.asyncio
async def test_basic_progress_bar(image_gen, mock_tag_info):
    """Test basic progress bar rendering."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "progress_bar",
            "x_start": 10,
            "y_start": 50,
            "x_end": 286,
            "y_end": 70,
            "progress": 75,
            "fill": "red",
            "outline": "black",
            "width": 1,
            "show_percentage": True
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(QR_CODE_IMG_PATH, 'progress_bar.png'))
        assert images_equal(generated_img, example_img), "Basic progress bar drawing failed"

@pytest.mark.asyncio
async def test_progress_bar_zero_progress(image_gen, mock_tag_info):
    """Test progress bar with zero progress rendering."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "progress_bar",
            "x_start": 10,
            "y_start": 50,
            "x_end": 286,
            "y_end": 70,
            "progress": 0,
            "fill": "red",
            "outline": "black",
            "width": 1,
            "show_percentage": True
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(QR_CODE_IMG_PATH, 'progress_bar_zero.png'))
        assert images_equal(generated_img, example_img), "Basic progress bar drawing failed"

@pytest.mark.asyncio
async def test_progress_bar_full(image_gen, mock_tag_info):
    """Test full progress bar rendering."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "progress_bar",
            "x_start": 10,
            "y_start": 50,
            "x_end": 286,
            "y_end": 70,
            "progress": 100,
            "fill": "red",
            "outline": "black",
            "background": "white",
            "width": 1,
            "show_percentage": True
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(QR_CODE_IMG_PATH, 'progress_bar_full.png'))
        assert images_equal(generated_img, example_img), "Full progress bar drawing failed"

@pytest.mark.asyncio
async def test_progress_bar_negative_progress(image_gen, mock_tag_info):
    """Test progress bar with negative progress rendering."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "progress_bar",
            "x_start": 10,
            "y_start": 50,
            "x_end": 286,
            "y_end": 70,
            "progress": -50,
            "fill": "red",
            "outline": "black",
            "width": 1,
            "show_percentage": True
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(QR_CODE_IMG_PATH, 'progress_bar_zero.png'))
        assert images_equal(generated_img, example_img), "Progress bar with negative percentage drawing failed"

@pytest.mark.asyncio
async def test_progress_bar_over_full(image_gen, mock_tag_info):
    """Test over full progress bar rendering."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "progress_bar",
            "x_start": 10,
            "y_start": 50,
            "x_end": 286,
            "y_end": 70,
            "progress": 150,
            "fill": "red",
            "outline": "black",
            "background": "white",
            "width": 1,
            "show_percentage": True
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(QR_CODE_IMG_PATH, 'progress_bar_full.png'))
        assert images_equal(generated_img, example_img), "Over full progress bar drawing failed"

@pytest.mark.asyncio
async def test_basic_progress_bar_percentage(image_gen, mock_tag_info):
    """Test basic progress bar with percentage rendering."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "progress_bar",
            "x_start": '20%',
            "y_start": '40%',
            "x_end": '80%',
            "y_end": '60%',
            "progress": 42,
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
        example_img = Image.open(os.path.join(QR_CODE_IMG_PATH, 'progress_bar_percentage.png'))
        assert images_equal(generated_img, example_img), "Basic progress bar with percentage drawing failed"