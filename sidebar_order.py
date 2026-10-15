"""Manual order of Dynamic and Fixed sessions in the Meetings sidebar.

Stored as one small JSON file next to the saved sessions:
{"dynamic": ["Name", ...], "fixed": ["Name", ...]}. Sessions missing from a
list simply appear after the listed ones, so new sessions never need an entry.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

KINDS = ("dynamic", "fixed")


class SidebarOrderError(ValueError):
    pass


def _clean_names(names: Iterable[str]) -> list[str]:
    result: list[str] = []

    for name in names:
        text = str(name).strip()
        if text and text not in result:
            result.append(text)

    return result


def load_order(path: Path) -> dict[str, list[str]]:
    """Missing or unreadable files mean no manual order yet."""
    order: dict[str, list[str]] = {kind: [] for kind in KINDS}

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return order

    if not isinstance(payload, dict):
        return order

    for kind in KINDS:
        raw = payload.get(kind)
        if isinstance(raw, list):
            order[kind] = _clean_names(raw)

    return order


def save_order(
    path: Path,
    kind: str,
    names: Iterable[str],
) -> dict[str, list[str]]:
    if kind not in KINDS:
        raise SidebarOrderError(f"Unknown session kind: {kind!r}.")

    path = Path(path)
    order = load_order(path)
    order[kind] = _clean_names(names)

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=".sidebar-order-", suffix=".tmp"
    )

    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(order, file, indent=2)
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise

    return order
