"""Tests that Home Assistant serves the bundled brand images.

Since 2026.3 the core ``brands`` component serves ``custom_components/<domain>/brand/`` itself
(the brands CDN no longer carries custom integrations), so this is what puts the Norman icon
in the integrations list. Older releases have no such component and are skipped.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.norman.const import DOMAIN

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("homeassistant.components.brands") is None,
    reason="Home Assistant older than 2026.3 has no brands component",
)

BRAND_DIR = Path(__file__).resolve().parent.parent / "custom_components" / DOMAIN / "brand"


@pytest.mark.parametrize(
    ("image", "served_file"),
    [
        ("icon.png", "icon.png"),
        ("icon@2x.png", "icon@2x.png"),
        ("logo.png", "logo.png"),
        ("logo@2x.png", "logo@2x.png"),
        # No dark variants are shipped; HA must fall back to the light ones
        ("dark_icon.png", "icon.png"),
        ("dark_logo@2x.png", "logo@2x.png"),
    ],
)
async def test_brand_images_are_served_from_the_integration(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    image: str,
    served_file: str,
) -> None:
    """Each brand image URL returns the file from brand/ (or its documented fallback)."""
    assert await async_setup_component(hass, "brands", {})
    client = await hass_client()

    response = await client.get(f"/api/brands/integration/{DOMAIN}/{image}")

    assert response.status == 200
    assert response.content_type == "image/png"
    assert await response.read() == (BRAND_DIR / served_file).read_bytes()
