"""Tests for ellipse rendering in ImageGen."""
import os
from io import BytesIO
import pytest
from unittest.mock import patch
from PIL import Image

from conftest import BASE_IMG_PATH, images_equal

ELLIPSE_IMG_PATH = os.path.join(BASE_IMG_PATH, 'ellipse')

@pytest.mark.asyncio
async def test_circle_ellipse(image_gen, mock_tag_info):
    """Test basic ellipse rendering."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "ellipse",
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
        example_img = Image.open(os.path.join(ELLIPSE_IMG_PATH, 'ellipse_drawing.png'))
        assert images_equal(generated_img, example_img), "Basic ellipse drawing failed"

@pytest.mark.asyncio
async def test_circle_ellipse_percentage(image_gen, mock_tag_info):
    """Test basic ellipse rendering with percentage."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "ellipse",
            "x_start": '20%',
            "y_start": '20%',
            "x_end": '80%',
            "y_end": '80%',
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
        example_img = Image.open(os.path.join(ELLIPSE_IMG_PATH, 'ellipse_drawing_percentage.png'))
        assert images_equal(generated_img, example_img), "Basic ellipse drawing failed"