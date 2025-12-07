"""Tests for text rendering in ImageGen."""
import os
from io import BytesIO
import pytest
from unittest.mock import patch
from PIL import Image

from conftest import BASE_IMG_PATH, images_equal, save_image, generate_test_image

TEXT_IMG_PATH = os.path.join(BASE_IMG_PATH, 'text')


@pytest.mark.asyncio
async def test_text_basic(image_gen, mock_tag_info):
    """Test basic text rendering with default settings."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "text",
            "x": 10,
            "y": 10,
            "value": "Hello, World!",
            "size": 20,
            "color": "black"
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await generate_test_image(image_gen, service_data)

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(TEXT_IMG_PATH, 'text_basic.png'))
        assert images_equal(generated_img, example_img), "Basic text rendering failed"


async def test_small_font_size(image_gen, mock_tag_info):
    """Test rendering text with a small font size."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "text",
            "x": 10,
            "y": 10,
            "value": "Tiny Text",
            "size": 3,
            "color": "black"
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await generate_test_image(image_gen, service_data)

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(TEXT_IMG_PATH, 'small_font.png'))
        assert images_equal(generated_img, example_img), "Small font size rendering failed"


async def test_large_font_size(image_gen, mock_tag_info):
    """Test rendering text with a large font size."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "text",
            "x": 10,
            "y": 10,
            "value": "Huge",
            "size": 150,
            "color": "black"
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await generate_test_image(image_gen, service_data)

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(TEXT_IMG_PATH, 'large_font.png'))
        assert images_equal(generated_img, example_img), "Large font size rendering failed"


async def test_text_wrapping(image_gen, mock_tag_info):
    """Test text wrapping."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "text",
            "x": 10,
            "y": 10,
            "value": "This is a long text that should wrap to multiple lines automatically",
            "size": 16,
            "color": "black",
            "max_width": 200
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await generate_test_image(image_gen, service_data)

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(TEXT_IMG_PATH, 'text_wrapping.png'))
        assert images_equal(generated_img, example_img), "Text wrapping failed"

async def test_text_wrapping_with_anchor(image_gen, mock_tag_info):
    """Test text wrapping with anchor."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "text",
            "x": "50%",
            "y": "50%",
            "value": "This is a long text that should wrap to multiple lines automatically",
            "size": 16,
            "color": "black",
            "max_width": 200,
            "anchor": "mm"
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await generate_test_image(image_gen, service_data)

        generated_img = Image.open(BytesIO(image_data))
        save_image(image_data)
        example_img = Image.open(os.path.join(TEXT_IMG_PATH, 'text_wrapping_anchor.png'))
        assert images_equal(generated_img, example_img), "Text wrapping failed"


async def test_text_with_special_characters(image_gen, mock_tag_info):
    """Test rendering text with special characters."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [
            {
                "type": "text",
                "x": 10,
                "y": 10,
                "value": "Special chars:",
                "size": 20,
            },
            {
                "type": "text",
                "x": 10,
                "y": 30,
                "value": "áéíóú ñ ¿¡ @#$%^&*",
                "size": 20,
            }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await generate_test_image(image_gen, service_data)

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(TEXT_IMG_PATH, 'text_special_chars.png'))
        assert images_equal(generated_img, example_img), "Special characters rendering failed"


@pytest.mark.asyncio
async def test_text_color_markup(image_gen, mock_tag_info):
    """Test text rendering with color markup."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [
            {
                "type": "text",
                "x": 10,
                "y": 10,
                "value": "Normal [red]Red Text[/red]",
                "size": 20,
                "parse_colors": True
            },
            {
                "type": "text",
                "x": 10,
                "y": 30,
                "value": "[red]Not Red Text[/red]",
                "size": 20,
                "parse_colors": False
            }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await generate_test_image(image_gen, service_data)

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(TEXT_IMG_PATH, 'text_color_markup.png'))
        assert images_equal(generated_img, example_img), "Color markup rendering failed"

@pytest.mark.asyncio
async def test_text_percentage(image_gen, mock_tag_info):
    """Test basic text rendering with percentage."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "text",
            "x": '10%',
            "y": '50%',
            "value": "Hello, World!",
            "size": '20%',
            "color": "black",
            "anchor": "lm"
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await generate_test_image(image_gen, service_data)

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(TEXT_IMG_PATH, 'text_percentage.png'))
        assert images_equal(generated_img, example_img), "Text with percentage rendering failed"

# @pytest.mark.asyncio
# async def test_text_alignment(image_gen, mock_tag_info):
#     """Test text alignment options."""
#     service_data = {
#         "background": "white",
#         "rotate": 0,
#         "payload": [
#             {
#                 "type": "text",
#                 "x": 150,
#                 "y": 10,
#                 "value": "Left Aligned",
#                 "size": 20,
#                 "align": "left"
#             },
#             {
#                 "type": "text",
#                 "x": 150,
#                 "y": 40,
#                 "value": "Center Aligned",
#                 "size": 20,
#                 "align": "center"
#             },
#             {
#                 "type": "text",
#                 "x": 150,
#                 "y": 70,
#                 "value": "Right Aligned",
#                 "size": 20,
#                 "align": "right"
#             }
#         ]
#     }
#
#     with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
#                return_value=mock_tag_info):
#         image_data = await image_gen.generate_custom_image(
#             "open_epaper_link.test_tag",
#             service_data
#         )
#
#         generated_img = Image.open(BytesIO(image_data))
#         save_image(image_data)
#         example_img = Image.open(os.path.join(TEXT_IMG_PATH, 'text_alignment.png'))
#         assert images_equal(generated_img, example_img), "Text alignment failed"

@pytest.mark.asyncio
async def test_text_anchors(image_gen, mock_tag_info):
    """Test different text anchor points."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [
            {
                "type": "text",
                "x": 150,
                "y": 10,
                "value": "Center Middle",
                "size": 20,
                "color": "black",
                "anchor": "mm"
            },
            {
                "type": "text",
                "x": 150,
                "y": 40,
                "value": "Bottom Right",
                "size": 20,
                "color": "black",
                "anchor": "rb"
            },
            {
                "type": "text",
                "x": 150,
                "y": 60,
                "value": "Top Left",
                "size": 20,
                "color": "black",
                "anchor": "lt"
            }
        ]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await generate_test_image(image_gen, service_data)

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(TEXT_IMG_PATH, 'text_anchors.png'))
        assert images_equal(generated_img, example_img), "Text anchor points failed"

@pytest.mark.asyncio
async def test_text_mixed_fonts(image_gen, mock_tag_info):
    """Test rendering text with different fonts in the same image."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [
            {
                "type": "text",
                "x": 10,
                "y": 10,
                "value": "Default Font",
                "size": 20,
                "color": "black"
            },
            {
                "type": "text",
                "x": 10,
                "y": 50,
                "value": "Alternate Font",
                "size": 20,
                "color": "black",
                "font": "rbm.ttf"
            }
        ]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await generate_test_image(image_gen, service_data)

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(TEXT_IMG_PATH, 'text_mixed_fonts.png'))
        assert images_equal(generated_img, example_img), "Mixed fonts rendering failed"

@pytest.mark.asyncio
async def test_text_empty_string(image_gen, mock_tag_info):
    """Test rendering empty text string."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "text",
            "x": 10,
            "y": 10,
            "value": "",
            "size": 20,
            "color": "black"
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await generate_test_image(image_gen, service_data)

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(BASE_IMG_PATH, 'blank.png'))
        assert images_equal(generated_img, example_img), "Empty text handling failed"

async def test_text_truncate(image_gen, mock_tag_info):
    """Test text truncation."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            "type": "text",
            "x": 10,
            "y": 10,
            "value": "This is a long text that should be truncated",
            "size": 16,
            "color": "black",
            "max_width": 150,
            "truncate": True
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await generate_test_image(image_gen, service_data)

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(TEXT_IMG_PATH, 'text_truncate.png'))
        assert images_equal(generated_img, example_img), "Text truncation failed"

# @pytest.mark.asyncio
# async def test_text_missing_x(image_gen, mock_tag_info):
#     """Test argument x missing."""
#     service_data = {
#         "background": "white",
#         "rotate": 0,
#         "payload": [{
#             "type": "text",
#             "y": 10,
#             "value": "Hello, World!",
#             "size": 20,
#             "color": "black"
#         }]
#     }
#
#     with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
#                return_value=mock_tag_info):
#         with pytest.raises(HomeAssistantError) as exc_info:
#             await image_gen.generate_custom_image(
#                 "open_epaper_link.test_tag",
#                 service_data
#             )
#         assert "Element 1: Element type 'text' missing required fields: x" in str(exc_info.value)
#
# @pytest.mark.asyncio
# async def test_text_missing_value(image_gen, mock_tag_info):
#     """Test argument value missing."""
#     service_data = {
#         "background": "white",
#         "rotate": 0,
#         "payload": [{
#             "type": "text",
#             "x": 10,
#             "y": 10,
#             "size": 20,
#             "color": "black"
#         }]
#     }
#
#     with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
#                return_value=mock_tag_info):
#         image_data = await image_gen.generate_custom_image(
#             "open_epaper_link.test_tag",
#             service_data
#         )
#
#         generated_img = Image.open(BytesIO(image_data))
#         example_img = Image.open(os.path.join(TEXT_IMG_PATH, 'text_basic.png'))
#         assert images_equal(generated_img, example_img), "Basic text rendering failed"