"""The tender a bid answers, as the comparison check (``domain.boq_tender_comparison``) reads it.

Found by :func:`app.services.tenders.tender_for` among the files of the bid's project and handed
to the checks through ``ValidationContext.tender``; the checks never look a file up themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.dataset import Dataset


@dataclass(frozen=True, slots=True)
class Tender:
    filename: str
    dataset: Dataset
