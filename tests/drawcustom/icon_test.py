"""Tests for icon rendering in ImageGen."""
import os

from conftest import BASE_IMG_PATH

ICON_IMG_PATH = os.path.join(BASE_IMG_PATH, 'icon')

# Icon tests do not work yet
# @pytest.mark.asyncio
# async def test_icon_basic(image_gen, mock_tag_info):
#     """Test basic icon rendering with default settings."""
#     service_data = {
#         "background": "white",
#         "rotate": 0,
#         "payload": [{
#             "type": "icon",
#             "x": 10,
#             "y": 10,
#             "size": 20,
#             "value": "mdi:home"
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
#         example_img = Image.open(os.path.join(ICON_IMG_PATH, 'icon_basic.png'))
#         assert images_equal(generated_img, example_img), "Basic icon rendering failed"