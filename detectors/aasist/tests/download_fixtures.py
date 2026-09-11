"""
Downloads 50 ASVspoof 2019 audio samples (25 bonafide, 25 spoofed)
from the official ASVspoof 2019 baseline sample repository (Yamagishi Lab)
and generates labels.csv for sanity-checking the AASIST model.
"""

import os
import csv
import urllib.request

BASE_URL = "https://nii-yamagishilab.github.io/samples-xin/"
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

# 25 authentic human samples from ASVspoof 2019
BONAFIDE_SAMPLES = [
    "samples-asvspoof2019/sample-human/p226_247.wav",
    "samples-asvspoof2019/sample-human/p228_227.wav",
    "samples-asvspoof2019/sample-human/p229_229.wav",
    "samples-asvspoof2019/sample-human/p231_234.wav",
    "samples-asvspoof2019/sample-human/p232_258.wav",
    "samples-asvspoof2019/sample-human/p233_252.wav",
    "samples-asvspoof2019/sample-human/p243_227.wav",
    "samples-asvspoof2019/sample-human/p250_240.wav",
    "samples-asvspoof2019/sample-human/p326_259.wav",
    "samples-asvspoof2019/sample-human/p254_281.wav",
    "samples-asvspoof2019/sample-human/p254_312.wav",
    "samples-asvspoof2019/sample-human/p254_349.wav",
    "samples-asvspoof2019/sample-human/p254_371.wav",
    "samples-asvspoof2019/sample-human/p256_225.wav",
    "samples-asvspoof2019/sample-human/p258_230.wav",
    "samples-asvspoof2019/sample-human/p265_230.wav",
    "samples-asvspoof2019/sample-human/p267_232.wav",
    "samples-asvspoof2019/sample-human/p272_233.wav",
    "samples-asvspoof2019/sample-human/p274_248.wav",
    "samples-asvspoof2019/sample-human/p280_237.wav",
    "samples-asvspoof2019/sample-human/p281_394.wav",
    "samples-asvspoof2019/sample-human/p293_360.wav",
    "samples-asvspoof2019/sample-human/p295_269.wav",
    "samples-asvspoof2019/sample-human/p300_244.wav",
    "samples-asvspoof2019/sample-human/p303_286.wav",
]

# 25 spoofed samples across multiple TTS (SS) and Voice Conversion (VC) attacks
SPOOF_SAMPLES = [
    "samples-asvspoof2019/sample-SS_1/p229_c0001.wav",
    "samples-asvspoof2019/sample-SS_1/p243_c0001.wav",
    "samples-asvspoof2019/sample-SS_1/p250_c0008.wav",
    "samples-asvspoof2019/sample-SS_2/p250_c0008.wav",
    "samples-asvspoof2019/sample-SS_2/p258_c0005.wav",
    "samples-asvspoof2019/sample-SS_3_new/p226_c0022.wav",
    "samples-asvspoof2019/sample-SS_3_new/p252_c0021.wav",
    "samples-asvspoof2019/sample-SS_4/p229_c0001.wav",
    "samples-asvspoof2019/sample-SS_4/p267_c0006.wav",
    "samples-asvspoof2019/sample-SS_5/p232_c0033.wav",
    "samples-asvspoof2019/sample-SS_5/p266_c0017.wav",
    "samples-asvspoof2019/sample-SS_6/p233_c0026.wav",
    "samples-asvspoof2019/sample-SS_6/p280_c0012.wav",
    "samples-asvspoof2019/sample-SS_7_new/p226_c0022.wav",
    "samples-asvspoof2019/sample-SS_7_new/p266_c0017.wav",
    "samples-asvspoof2019/sample-SS_8_new/p274_c0023.wav",
    "samples-asvspoof2019/sample-SS_8_new/p317_c0019.wav",
    "samples-asvspoof2019/sample-VC_1/p243_p254_312.wav",
    "samples-asvspoof2019/sample-VC_1/p323_p265_230.wav",
    "samples-asvspoof2019/sample-VC_2/p226_p281_394.wav",
    "samples-asvspoof2019/sample-VC_2/p317_p228_227.wav",
    "samples-asvspoof2019/sample-VC_3_new/p232_p360_305.wav",
    "samples-asvspoof2019/sample-VC_3_new/p266_p343_257.wav",
    "samples-asvspoof2019/sample-VC_4/p258_p254_371.wav",
    "samples-asvspoof2019/sample-VC_5/p232_p360_305.wav",
]


def download_fixtures():
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    labels_file = os.path.join(FIXTURES_DIR, "labels.csv")
    
    rows = [["filename", "label", "attack_type"]]
    
    print(f"Downloading {len(BONAFIDE_SAMPLES)} bonafide samples...")
    for rel_path in BONAFIDE_SAMPLES:
        fname = os.path.basename(rel_path)
        dest_path = os.path.join(FIXTURES_DIR, f"bonafide_{fname}")
        url = BASE_URL + rel_path
        if not os.path.exists(dest_path):
            try:
                urllib.request.urlretrieve(url, dest_path)
            except Exception as e:
                print(f"Failed to download {url}: {e}")
                continue
        rows.append([f"bonafide_{fname}", "bonafide", "human"])

    print(f"Downloading {len(SPOOF_SAMPLES)} spoofed samples...")
    for rel_path in SPOOF_SAMPLES:
        fname = os.path.basename(rel_path)
        attack = rel_path.split("/")[1].replace("sample-", "")
        dest_path = os.path.join(FIXTURES_DIR, f"spoof_{attack}_{fname}")
        url = BASE_URL + rel_path
        if not os.path.exists(dest_path):
            try:
                urllib.request.urlretrieve(url, dest_path)
            except Exception as e:
                print(f"Failed to download {url}: {e}")
                continue
        rows.append([f"spoof_{attack}_{fname}", "spoof", attack])

    with open(labels_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    print(f"Downloaded fixtures successfully. Total labeled rows: {len(rows)-1}")
    print(f"Labels saved to: {labels_file}")


if __name__ == "__main__":
    download_fixtures()
