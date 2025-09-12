"""Tests for qr code rendering in ImageGen."""
import os
from io import BytesIO
import pytest
from unittest.mock import patch
from PIL import Image

from conftest import BASE_IMG_PATH, images_equal

QR_CODE_IMG_PATH = os.path.join(BASE_IMG_PATH, 'qr_code')

@pytest.mark.asyncio
async def test_basic_qr_code(image_gen, mock_tag_info):
    """Test basic qr code rendering."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "qrcode",
            "x": 5,
            "y": 10,
            "data": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "color": "black",
            "bgcolor": "white",
            "boxsize": 3,
            "border": 1
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(QR_CODE_IMG_PATH, 'qr_code.png'))
        assert images_equal(generated_img, example_img), "Basic qr code drawing failed"

@pytest.mark.asyncio
async def test_long_qr_code(image_gen, mock_tag_info):
    """Test qr code with long data rendering."""
    long_data = "https://example.com/" + "a" * 1000
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "qrcode",
            "x": 10,
            "y": 10,
            "data": long_data,
            "color": "black",
            "bgcolor": "white",
            "boxsize": 3,
            "border": 4
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(QR_CODE_IMG_PATH, 'qr_code_long.png'))
        assert images_equal(generated_img, example_img), "Long qr code drawing failed"

@pytest.mark.asyncio
async def test_basic_qr_code_percentage(image_gen, mock_tag_info):
    """Test basic qr code rendering with percentage."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "qrcode",
            "x": '10%',
            "y": '10%',
            "data": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "color": "black",
            "bgcolor": "white",
            "boxsize": 3,
            "border": 1
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(QR_CODE_IMG_PATH, 'qr_code_percentage.png'))
        assert images_equal(generated_img, example_img), "Basic qr code drawing with percentage failed"