import pytest
from PIL import Image
from fsmart.config import Settings
from fsmart.models import Models


def test_fast_style_torch_preserves_aspect_and_crops_padding(tmp_path, monkeypatch):
    torch = pytest.importorskip('torch')
    monkeypatch.setenv('FSM_STYLE_BACKEND', 'torch')
    model = Models(Settings(data_dir=tmp_path/'runtime'))
    model._torch, model.device = torch, torch.device('cpu')
    seen = []

    def net(x):
        seen.append(tuple(x.shape))
        return x + 10

    monkeypatch.setattr(model, 'load_style', lambda style: net)
    # Non-multiple-of-four input must never stretch to the padded shape.
    output = model.preset(Image.new('RGB', (17, 65), (100, 120, 140)), 'mosaic', .5, lambda *a: None)
    assert seen == [(1, 3, 68, 20)]
    assert output.size == (17, 65) and output.getpixel((0, 0)) == (105, 125, 145)
    output = model.preset(Image.new('RGB', (2500, 1200)), 'mosaic', .8, lambda *a: None)
    assert output.size == (512, 246)
    assert model.fast_style.backend == 'pytorch-cpu'
    with pytest.raises(ValueError):
        model.preset(Image.new('RGB', (32, 32)), 'mosaic', .8, lambda *a: None, profile='unbounded')
