from __future__ import annotations
from pathlib import Path


def find_register(root: str | Path) -> Path | None:
    root = Path(root)
    if root.is_file():
        return root
    if not root.exists():
        return None
    candidates = [p for p in root.glob("접수대장*.xlsm") if not p.name.startswith("~$")]
    if not candidates:
        candidates = [p for p in root.glob("*.xlsm") if not p.name.startswith("~$")]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def newest_management_file(directory: str | Path) -> Path | None:
    directory = Path(directory)
    if not directory.exists():
        return None
    files = [
        p for p in directory.glob("성적서발행발송리스트*")
        if p.suffix.lower() in {".xls", ".xlsx"} and not p.name.startswith("~$")
    ]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None
