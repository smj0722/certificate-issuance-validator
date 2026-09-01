from __future__ import annotations
import json
import urllib.request
from . import __version__

RELEASES_API_URL = "https://api.github.com/repos/smj0722/certificate-issuance-validator/releases/latest"


def check_update(timeout: float = 4.0) -> tuple[bool, str, str]:
    req = urllib.request.Request(RELEASES_API_URL, headers={"User-Agent": "certificate-issuance-validator"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    latest = str(data.get("tag_name", "")).lstrip("v")
    url = str(data.get("html_url", ""))
    return latest not in {"", __version__}, latest, url
