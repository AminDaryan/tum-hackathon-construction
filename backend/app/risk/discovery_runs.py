"""The store of discovery runs: one JSON file per run under ``<data_dir>/risk_discovery``.

shortcut: files, not the database (no migration), and an in-process lock: two server processes
could each start the same discovery once. Upgrade to a table with a row lock when the server
runs as several processes.
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

from app.risk.models import DiscoveryRun

LOCK = threading.RLock()  # decides "reuse or start" and guards the end of a run
ACTIVE: set[str] = set()  # ids of the runs this process is working on
_ID = re.compile(r"disc_[A-Za-z0-9]{1,64}")
# Windows refuses to replace a file while another thread has it open or is replacing it too
# (PermissionError, "Access is denied"); that clears within milliseconds, so the replacement
# is tried again a few times. Elsewhere a PermissionError is real and is raised after the tries.
REPLACE_ATTEMPTS = 20
REPLACE_PAUSE_SECONDS = 0.01


def replace(source: Path, target: Path) -> None:
    """``os.replace``, tried again while Windows reports the target as in use."""
    for attempt in range(1, REPLACE_ATTEMPTS + 1):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS:
                raise
            time.sleep(REPLACE_PAUSE_SECONDS)


class DiscoveryRunStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, run: DiscoveryRun) -> None:
        """Write the run whole (a reader never sees half a file)."""
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(run.discovery_run_id)
        part = path.with_name(f".{path.name}.{threading.get_ident()}.part")
        part.write_text(run.model_dump_json(), encoding="utf-8")
        replace(part, path)

    def get(self, discovery_run_id: str) -> DiscoveryRun | None:
        if _ID.fullmatch(discovery_run_id) is None:  # never a path from the request
            return None
        path = self._path(discovery_run_id)
        if not path.is_file():
            return None
        return DiscoveryRun.model_validate_json(path.read_text(encoding="utf-8"))

    def for_run(self, run_id: str) -> list[DiscoveryRun]:
        """The runs of one validation run, newest first."""
        # shortcut: reads every stored run; fine for the few runs of a review, index them in a
        # table when there are thousands.
        if not self.root.is_dir():
            return []
        runs = [
            DiscoveryRun.model_validate_json(path.read_text(encoding="utf-8"))
            for path in self.root.glob("disc_*.json")
        ]
        mine = [r for r in runs if r.run_id == run_id]
        return sorted(mine, key=lambda r: (r.requested_at, r.discovery_run_id), reverse=True)

    def _path(self, discovery_run_id: str) -> Path:
        return self.root / f"{discovery_run_id}.json"
