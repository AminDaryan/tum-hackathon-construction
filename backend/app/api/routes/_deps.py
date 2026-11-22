"""Shared helpers of the routers."""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated
from urllib.parse import quote

from fastapi import Query, Request

from app.services.workbench import Workbench

# The largest offset every backend can bind: a signed 64-bit integer (SQLite INTEGER,
# PostgreSQL bigint). A larger one is a malformed request (422), not a failed query (500).
MAX_OFFSET = 2**63 - 1
Offset = Annotated[int, Query(ge=0, le=MAX_OFFSET)]


def workbench(request: Request) -> Workbench:
    service: Workbench = request.app.state.workbench  # set by create_app; State is untyped
    return service


def content_disposition(filename: str) -> str:
    """``attachment`` with an ASCII fallback name and the exact UTF-8 name (RFC 6266)."""
    folded = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    fallback = re.sub(r"[^A-Za-z0-9._ -]", "_", folded).strip() or "export"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"
