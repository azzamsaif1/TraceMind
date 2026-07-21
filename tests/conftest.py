import io

import pytest
from PIL import Image, ImageDraw


def _png(color, size=(128, 128), text=None):
    img = Image.new("RGB", size, color=color)
    if text:
        ImageDraw.Draw(img).text((5, 5), text, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def blue_png():
    return _png((30, 60, 160))


@pytest.fixture
def blue_png_variant():
    # Same base colour, slight change -> small perceptual-hash distance.
    return _png((30, 60, 160), text="v2")


@pytest.fixture
def red_png():
    return _png((200, 20, 20))


@pytest.fixture
def make_png():
    return _png
