"""Deterministic photo finishes; these are colour treatments, not generative AI."""
from PIL import Image, ImageEnhance, ImageOps

LOOKS = [
    {'id': 'original', 'name': 'Nguyên bản', 'description': 'Giữ màu gốc'},
    {'id': 'cinema', 'name': 'Cinema', 'description': 'Bóng xanh, vùng sáng ấm'},
    {'id': 'portra', 'name': 'Soft film', 'description': 'Mềm, ấm, giảm tương phản'},
    {'id': 'noir', 'name': 'Noir', 'description': 'Đen trắng tương phản'},
    {'id': 'cool', 'name': 'Nordic', 'description': 'Lạnh nhẹ, dịu màu'},
    {'id': 'sunset', 'name': 'Golden hour', 'description': 'Sắc vàng và vùng sáng ấm'},
]


def finish(image, look, strength):
    image = image.convert('RGB')
    if look == 'original' or strength == 0:
        return image.copy()
    if look == 'noir':
        result = ImageEnhance.Contrast(ImageOps.grayscale(image).convert('RGB')).enhance(1.22)
    else:
        saturation, contrast, gains, lifts = {
            'cinema': (.82, 1.12, (1.06, 1., .92), (0, 2, 9)),
            'portra': (.86, .88, (1.04, 1.01, .96), (7, 5, 3)),
            'cool': (.72, .97, (.96, 1.01, 1.06), (2, 3, 5)),
            'sunset': (1.08, 1.04, (1.09, 1.02, .90), (4, 1, 0)),
        }[look]
        result = ImageEnhance.Color(image).enhance(saturation)
        result = ImageEnhance.Contrast(result).enhance(contrast)
        channels = result.split()
        result = Image.merge('RGB', [channel.point([max(0, min(255, round(v * gain + lift * (1 - v / 255)))) for v in range(256)])
                                     for channel, gain, lift in zip(channels, gains, lifts)])
    return Image.blend(image, result, strength)
