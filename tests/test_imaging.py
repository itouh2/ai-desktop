from PIL import Image

from ai_desktop.imaging import build_meta, encode_jpeg, fit_size, image_to_screen, shrink


def test_fit_size_shrinks_landscape_to_max_edge():
    width, height, scale = fit_size(3840, 2560)
    assert (width, height) == (1568, 1045)
    assert scale == 1568 / 3840


def test_fit_size_shrinks_portrait_to_max_edge():
    width, height, scale = fit_size(1000, 3000)
    assert (width, height) == (523, 1568)
    assert scale == 1568 / 3000


def test_fit_size_keeps_exact_max_edge():
    assert fit_size(1568, 1000) == (1568, 1000, 1.0)


def test_fit_size_never_upscales():
    assert fit_size(800, 600) == (800, 600, 1.0)


def test_fit_size_keeps_at_least_one_pixel():
    width, height, _ = fit_size(10000, 1)
    assert (width, height) == (1568, 1)


def test_shrink_resizes_large_image():
    image, scale = shrink(Image.new("RGB", (3000, 1000)))
    assert image.size == (1568, 523)
    assert scale == 1568 / 3000


def test_shrink_leaves_small_image_untouched():
    original = Image.new("RGB", (800, 600))
    image, scale = shrink(original)
    assert image is original
    assert scale == 1.0


def test_encode_jpeg_accepts_rgba():
    data = encode_jpeg(Image.new("RGBA", (10, 10), (255, 0, 0, 128)))
    assert data[:2] == b"\xff\xd8"


def test_build_meta_matches_spec_keys():
    meta = build_meta("window:42 Book1 - Excel", 120, 80, (1600, 900), (1568, 882), 0.98)
    assert meta == {
        "source": "window:42 Book1 - Excel",
        "originX": 120,
        "originY": 80,
        "originalWidth": 1600,
        "originalHeight": 900,
        "imageWidth": 1568,
        "imageHeight": 882,
        "scale": 0.98,
    }


def test_image_to_screen_applies_origin_and_scale():
    meta = build_meta("monitor:3", -2160, -1255, (2160, 3840), (1080, 1920), 0.5)
    assert image_to_screen(meta, 100, 50) == (-1960, -1155)
    _, _, scale = fit_size(3840, 2560)
    corner = build_meta("monitor:1", 0, 0, (3840, 2560), (1568, 1045), scale)
    assert image_to_screen(corner, 1568, 0) == (3840, 0)


def test_image_to_screen_can_use_a_newer_origin():
    meta = build_meta("window:42 Excel", -100, 50, (1600, 900), (800, 450), 0.5)
    assert image_to_screen(meta, 10, 20) == (-80, 90)
    assert image_to_screen(meta, 10, 20, origin=(300, 400)) == (320, 440)
