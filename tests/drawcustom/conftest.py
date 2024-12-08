"""Shared fixtures for drawcustom tests."""
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock

from PIL import ImageChops

from homeassistant.core import HomeAssistant
from custom_components.open_epaper_link.imagegen import ImageGen

current_dir = os.path.dirname(os.path.abspath(__file__))
BASE_IMG_PATH = os.path.join(current_dir, "test_images")

@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)

    # Mock async_add_executor_job
    hass.async_add_executor_job = AsyncMock()

    # Mock async_create_task to properly await coroutines
    async def mock_create_task(coro):
        await coro
        return None
    hass.async_create_task = mock_create_task

    return hass

@pytest.fixture
def mock_tag_info():
    """Create a mock tag type info."""
    tag_type = MagicMock()
    tag_type.width = 296
    tag_type.height = 128
    tag_type.color_table = {
        "white": [255, 255, 255],
        "black": [0, 0, 0],
        "red": [255, 0, 0],
        "accent": [255, 0, 0]
    }
    return tag_type, "red"

@pytest.fixture
def image_gen(mock_hass):
    """Create an ImageGen instance with mocked Home Assistant."""
    return ImageGen(mock_hass)

# Helper functions that might be needed across multiple test files
def get_test_image_path(filename):
    """Get the full path to a test image file."""
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_images", filename)

def mock_service_data(payload):
    """Create a standard service data structure with given payload."""
    return {
        "background": "white",
        "rotate": 0,
        "dither": 2,
        "payload": payload
    }

def images_equal(img1, img2):
    """Compare two images and return True if they are identical."""
    return ImageChops.difference(img1, img2).getbbox() is None

def save_image(image_bytes):
    """Save image for debugging."""
    img_path = os.path.join(BASE_IMG_PATH, 'rename_me.png')
    with open(img_path, 'wb') as f:
        f.write(image_bytes)


# Setup and cleanup code that runs before and after each test session
def pytest_sessionstart(session):
    """
    Called after the Session object has been created and
    before performing collection and entering the run test loop.
    """
    # Create test_images directory if it doesn't exist
    test_images_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_images")
    os.makedirs(test_images_dir, exist_ok=True)

def pytest_sessionfinish(session, exitstatus):
    """
    Called after whole test run finished, right before
    returning the exit status to the system.
    """
    pass  # Add any cleanup code if needed