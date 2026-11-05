"""Real VGG19 check that different style paintings give clearly different results (skipped without the weights)."""
import numpy as np
import pytest
from PIL import Image, ImageDraw

from fsmart.config import Settings


def weights():
    settings = Settings()
    if not (settings.weights_dir / 'style/vgg19-dcbb9e9d.pth').is_file():
        pytest.skip('VGG19 weights not installed')
    return settings


def stripes(colors, width=12):
    image = Image.new('RGB', (256, 192)); draw = ImageDraw.Draw(image)
    for i in range(0, 256 + 192, width):
        draw.line([(i, 0), (i - 192, 192)], fill=colors[(i // width) % len(colors)], width=width)
    return image


def test_two_paintings_give_two_different_results_that_take_their_colours(tmp_path):
    from fsmart.models import Models
    settings = weights()
    models = Models(Settings(weights_dir=settings.weights_dir, data_dir=tmp_path))
    gradient = np.dstack(np.meshgrid(np.linspace(60, 200, 320), np.linspace(60, 200, 240)) + [np.full((240, 320), 128.)]).astype(np.uint8)
    photo = Image.fromarray(gradient)
    warm = stripes([(230, 40, 20), (250, 200, 30)])
    cool = stripes([(20, 60, 200), (10, 160, 150)])
    a = np.asarray(models.custom(photo, warm, .8, 30, lambda *_: None), np.float32)
    b = np.asarray(models.custom(photo, cool, .8, 30, lambda *_: None), np.float32)
    assert np.abs(a - b).mean() > 20                      # the old transfer gave near-identical outputs here
    assert a[..., 0].mean() > b[..., 0].mean() + 15       # warm painting → redder result
    assert b[..., 2].mean() > a[..., 2].mean() + 15       # cool painting → bluer result
