"""``documents.upload_form``: the upload service behind ``POST /documents``."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.errors import InvalidInputError
from app.models.dataset import MappingMethod
from app.models.schema import SchemaDecisions, TableDecisions
from app.services import documents
from app.services.workbench import Workbench
from tests.unit.api.conftest import make_workbench

CSV = b"Pos;Text;Menge;Einheit;EP;GP\n1;Beton;2;m3;10,00;20,00\n"


class Form:
    """An already parsed upload form; ``finish`` may fail like a malformed body does."""

    def __init__(self, fields: dict[str, str], *, fail: Exception | None = None) -> None:
        self.filename: str | None = None
        self.fields = fields
        self.fail = fail
        self.finished = False

    def file_chunks(self) -> Iterator[bytes]:
        self.filename = "Angebot.csv"
        yield CSV[:10]
        yield CSV[10:]

    def finish(self) -> dict[str, str]:
        self.finished = True
        if self.fail is not None:
            raise self.fail
        return self.fields


@pytest.fixture
def workbench(tmp_path: Path) -> Workbench:
    return make_workbench(tmp_path)


def test_the_file_is_stored_and_the_form_names_the_profile(workbench: Workbench) -> None:
    form = Form({"profile_id": "generic"})
    detail = documents.upload_form(workbench, form)
    assert form.finished
    assert detail.document.original_filename == "Angebot.csv"
    assert detail.document.profile_id == "generic" and detail.document.size_bytes == len(CSV)
    assert detail.dataset is not None and detail.dataset.document_id == detail.document.document_id
    with workbench.uow() as uow:
        assert uow.documents.get(detail.document.document_id) is not None


def test_without_a_profile_the_default_profile_is_used(workbench: Workbench) -> None:
    detail = documents.upload_form(workbench, Form({"profile_id": ""}))
    assert detail.document.profile_id == workbench.settings.default_profile_id


@pytest.mark.parametrize(
    ("form", "error"),
    [
        (Form({}, fail=InvalidInputError("The multipart body ended early.")), InvalidInputError),
        (Form({"profile_id": "nope"}), InvalidInputError),
    ],
    ids=["malformed form", "unknown profile"],
)
def test_a_rejected_form_stores_nothing(
    workbench: Workbench, tmp_path: Path, form: Form, error: type[Exception]
) -> None:
    with pytest.raises(error):
        documents.upload_form(workbench, form)
    assert list((tmp_path / "tmp").iterdir()) == []  # the spool was discarded
    with workbench.uow() as uow:
        assert uow.documents.list(offset=0, limit=10).total == 0


def test_upload_applies_the_reviewer_decisions_it_is_given(workbench: Workbench) -> None:
    content = b"Pos;Text;STLB-Bau;Menge;Einheit;EP;GP\n1;Beton;013.456;2;m3;10,00;20,00\n"
    _, plain = documents.upload(workbench, filename="ohne.csv", chunks=[content], profile_id="boq")
    assert plain is not None and plain.tables[0].column_for_field("standard_text_key") is None
    reviewer = SchemaDecisions(
        tables=[TableDecisions(sheet_index=0, column_fields={3: "standard_text_key"})]
    )
    _, dataset = documents.upload(
        workbench, filename="mit.csv", chunks=[content], profile_id="boq", decisions=reviewer
    )
    assert dataset is not None
    column = dataset.tables[0].column_for_field("standard_text_key")
    assert column is not None and column.original_header == "STLB-Bau"
    assert column.mapping is not None and column.mapping.method is MappingMethod.USER
    assert "decisions_applied" in [w.code for w in dataset.extraction.warnings]
