import json
import os
import jsonschema
from Schema import DETECTOR_MANIFEST_SCHEMA

MANIFEST_DIR = os.path.dirname(__file__)
FILES = ["video-classifier.json", "aasist.json", "rppg.json", "syncnet.json"]

def main():
    all_valid = True
    for filename in FILES:
        path = os.path.join(MANIFEST_DIR, filename)
        if not os.path.exists(path):
            print(f"❌ {filename}: FILE MISSING")
            all_valid = False
            continue
        try:
            with open(path) as f:
                data = json.load(f)
            jsonschema.validate(instance=data, schema=DETECTOR_MANIFEST_SCHEMA)
            print(f"✅ {filename}: VALID")
        except jsonschema.exceptions.ValidationError as e:
            print(f"❌ {filename}: INVALID — {e.message}")
            all_valid = False
        except json.JSONDecodeError as e:
            print(f"❌ {filename}: MALFORMED JSON — {e}")
            all_valid = False

    print("\nAll manifests valid!" if all_valid else "\nSome manifests need fixing.")

if __name__ == "__main__":
    main()