"""One JSON file per dataset under a folder of the data directory: what a model answered about
the dataset (material matches, the bill review), kept so that later runs do not ask again.

shortcut: plain files and an in-process lock; two server processes could both write one.
Upgrade to a table when the server runs as several processes.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

from app.risk.discovery_runs import replace
from app.services.workbench import Workbench

LOCK = threading.Lock()
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")


def read(wb: Workbench, folder: str, dataset_id: str) -> str | None:
    """The stored text of a dataset, ``None`` when there is none."""
    path = _path(wb, folder, dataset_id)
    if path is None or not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def write(wb: Workbench, folder: str, dataset_id: str, text: str) -> None:
    """Write the file whole (a reader never sees half a file)."""
    path = _path(wb, folder, dataset_id)
    if path is None:  # pragma: no cover - dataset ids are generated
        raise ValueError("unexpected dataset id")
    with LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(f".{path.name}.{threading.get_ident()}.part")
        part.write_text(text, encoding="utf-8")
        replace(part, path)


def _path(wb: Workbench, folder: str, dataset_id: str) -> Path | None:
    if _ID.fullmatch(dataset_id) is None:  # never a path from a request
        return None
    return wb.settings.data_dir / folder / f"{dataset_id}.json"
