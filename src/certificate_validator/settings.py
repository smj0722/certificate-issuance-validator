from __future__ import annotations
import json
from pathlib import Path

APP_DIR = Path.home() / "AppData" / "Local" / "성적서 발급검증"
SETTINGS_FILE = APP_DIR / "settings.json"
HISTORY_FILE = APP_DIR / "history.json"

DEFAULTS = {
    "register_root": r"Z:\\",
    "last_download_dir": str(Path.home() / "Downloads"),
}


def load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return {**DEFAULTS, **data}
    except Exception:
        return dict(DEFAULTS)


def save_settings(settings: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def append_history(item: dict, keep: int = 100) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    if HISTORY_FILE.exists():
        try:
            rows = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            rows = []
    rows.insert(0, item)
    HISTORY_FILE.write_text(json.dumps(rows[:keep], ensure_ascii=False, indent=2), encoding="utf-8")
