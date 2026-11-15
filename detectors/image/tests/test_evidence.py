import numpy as np
from PIL import Image
from evidence.frequency_check import check_frequency
from evidence.exif_check import check_exif


def test_frequency_on_real_pattern():
    arr = np.random.randint(0, 255, (256, 256, 3), dtype=np.uint8)
    img = Image.fromarray(arr)
    res = check_frequency(img)
    assert "flag" in res
    assert "peak_ratio" in res


def test_frequency_on_grid_artifact():
    arr = np.zeros((256, 256, 3), dtype=np.uint8)
    for i in range(256):
        for j in range(256):
            if (i // 8 + j // 8) % 2 == 0:
                arr[i, j] = 255
    res = check_frequency(Image.fromarray(arr))
    assert res["flag"] is True
    assert res["peak_ratio"] > 4.0


def test_exif_on_synthetic_image():
    img = Image.new("RGB", (64, 64))
    res = check_exif(img)
    assert res["exif_missing"] is True
    assert res["software_tag_present"] is False