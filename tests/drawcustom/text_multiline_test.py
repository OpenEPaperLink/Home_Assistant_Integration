"""Tests for text multiline rendering in ImageGen."""
import os
from io import BytesIO
import pytest
from unittest.mock import patch
from PIL import Image

from conftest import BASE_IMG_PATH, images_equal, save_image

TEXT_MULTILINE_IMG_PATH = os.path.join(BASE_IMG_PATH, 'text_multiline')


@pytest.mark.asyncio
async def test_text_multiline_basic(image_gen, mock_tag_info):
    """Test basic text multiline rendering with default settings."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            'type': 'text',
            'x': 10,
            'y': 10,
            'value': 'Hello,\nWorld!',
            'size': 18,
            'color': 'red',
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))

        example_img = Image.open(os.path.join(TEXT_MULTILINE_IMG_PATH, 'text_multiline.png'))
        assert images_equal(generated_img, example_img), "Basic text rendering failed"

@pytest.mark.asyncio
async def test_text_multiline_delimiter(image_gen, mock_tag_info):
    """Test multiline with delimiter rendering settings."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            'type': 'multiline',
            'x': 10,
            'y': 10,
            'value': 'Line 1|Line 2|Line 3',
            'size': 18,
            'color': 'black',
            'delimiter': '|',
            'offset_y': 25
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))

        example_img = Image.open(os.path.join(TEXT_MULTILINE_IMG_PATH, 'text_multiline_delimiter.png'))
        assert images_equal(generated_img, example_img), "Multiline text with delimiter rendering failed"

@pytest.mark.asyncio
async def test_text_multiline_empty_line(image_gen, mock_tag_info):
    """Test multiline with empty line rendering settings."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            'type': 'multiline',
            'x': 10,
            'y': 10,
            'value': 'Line 1||Line 3',
            'size': 18,
            'color': 'black',
            'delimiter': '|',
            'offset_y': 25
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        example_img = Image.open(os.path.join(TEXT_MULTILINE_IMG_PATH, 'multiline_empty_line.png'))
        assert images_equal(generated_img, example_img), "Multiline text with empty line rendering failed"

@pytest.mark.asyncio
async def test_text_multiline_delimiter_and_newline(image_gen, mock_tag_info):
    """Test multiline with delimiter and newline rendering settings."""
    service_data = {
        "background": "white",
        "rotate": 0,
        "payload": [{
            'type': 'multiline',
            'x': 10,
            'y': 10,
            'value': 'Line 1\nNewline|Line 2\nNewline|Line 3',
            'size': 18,
            'color': 'black',
            'delimiter': '|',
            'offset_y': 25
        }]
    }

    with patch('custom_components.open_epaper_link.imagegen.ImageGen.get_tag_info',
               return_value=mock_tag_info):
        image_data = await image_gen.generate_custom_image(
            "open_epaper_link.test_tag",
            service_data
        )

        generated_img = Image.open(BytesIO(image_data))
        save_image(image_data)
        example_img = Image.open(os.path.join(TEXT_MULTILINE_IMG_PATH, 'text_multiline_delimiter_and_newline.png'))
        assert images_equal(generated_img, example_img), "Multiline text with delimiter and newline rendering failed"

# @pytest.mark.asyncio
# async def test_calendar_format_multiline(image_gen, mock_tag_info):
#     """Test calendar format with multiline text and potential blank lines."""
#     service_data = {
#         "background": "white",
#         "rotate": 0,
#         "payload": [{
#             "type": "multiline",
#             "value": "#Ganztags: St. Martin\n#11:00-15:00 OGTS\n#11:30-12:30 Abgabe Arbeitsblatt\n#15:00-16:00 J1 Untersuchung",
#             "font": "ppb.ttf",  # Using default test font instead of Noto
#             "x": 6,
#             "start_y": 262,
#             "offset_y": 36,
#             "delimiter": "#",
#             "size": 36,
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
#         save_image(image_data)
#         example_img = Image.open(os.path.join(TEXT_MULTILINE_IMG_PATH, 'calendar_format.png'))
#         assert images_equal(generated_img, example_img), "Calendar format multiline rendering failed"
#
# @pytest.mark.asyncio
# async def test_multiline_with_blank_lines(image_gen, mock_tag_info):
#     """Test handling of blank lines in multiline text."""
#     service_data = {
#         "background": "white",
#         "rotate": 0,
#         "payload": [{
#             "type": "multiline",
#             "value": "#Line 1\n#\n#Line 3\n#Line 4",
#             "font": "ppb.ttf",
#             "x": 10,
#             "start_y": 10,
#             "offset_y": 25,
#             "delimiter": "#",
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
#         example_img = Image.open(os.path.join(TEXT_MULTILINE_IMG_PATH, 'multiline_blank_lines.png'))
#         assert images_equal(generated_img, example_img), "Multiline text with blank lines rendering failed"
#
# @pytest.mark.asyncio
# async def test_multiline_whitespace_handling(image_gen, mock_tag_info):
#     """Test handling of whitespace in multiline text."""
#     service_data = {
#         "background": "white",
#         "rotate": 0,
#         "payload": [{
#             "type": "multiline",
#             "value": "#  Line with leading spaces\n#Line without spaces\n#\tLine with tab\n#Line with trailing spaces  ",
#             "font": "ppb.ttf",
#             "x": 10,
#             "start_y": 10,
#             "offset_y": 25,
#             "delimiter": "#",
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
#         example_img = Image.open(os.path.join(TEXT_MULTILINE_IMG_PATH, 'multiline_whitespace.png'))
#         assert images_equal(generated_img, example_img), "Multiline text whitespace handling failed"