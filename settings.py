import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULTS = {
    "output_dir": os.path.abspath("./downloads"),
    "max_concurrent_downloads": 2,
    "default_lang": "en",
    "default_cbz": True,
    "default_data_saver": False,
    "volume_group_size": 10,
    "export_format": "cbz",   # cbz / epub / pdf
}


def load_settings() -> dict:
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(DEFAULTS)
            merged.update(data)
            return merged
        except Exception:
            pass
    return dict(DEFAULTS)


def save_settings(settings: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
