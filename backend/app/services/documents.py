"""Documents: upload (spool, check, store, extract, normalize) and the document summaries.

The API route parses the streaming multipart body (``app.api.multipart``) and hands the form to
:func:`upload_form`, which spools the file part while it arrives and calls :func:`ingest`;
:func:`upload` does the same for callers that hold the bytes. An upload with an unknown profile,
a malformed form or a file that fails a security or format check is discarded and never stored
(4xx). A stored file whose extraction fails is kept with ``processing_status = failed`` and a
reason, and has no dataset (the API still answers 201).

:func:`upload` and :func:`ingest` also take reviewer decisions (``SchemaDecisions``), laid over
the structure the file declares, for callers that already know them; the API does not accept
them yet (the extraction review arrives later). The benchmark harness uses them to map the
columns that no header maps, as a reviewer would.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Protocol

from app.core.errors import InvalidInputError, NotFoundError, WorkbenchError
from app.core.ids import IdPrefix
from app.ingestion.ifc import read_takeoff
from app.ingestion.security import sanitize_filename, validate_upload
from app.models.audit import AuditAction, EntityType
from app.models.dataset import Dataset, ExtractionQuality
from app.models.document import AttachedModel, Document, ProcessingStatus
from app.models.model_takeoff import ModelTakeoff
from app.models.profile import DomainProfile
from app.models.schema import SchemaDecisions
from app.normalization.builder import build_dataset
from app.repositories.base import UnitOfWork
from app.schemas.documents import (
    DocumentDetail,
    DocumentPage,
    DocumentSummary,
    LastRunSummary,
    ModelInfo,
)
from app.services import datasets
from app.services.workbench import Workbench
from app.storage.file_store import SpooledUpload

logger = logging.getLogger(__name__)
MAX_FAILURE_REASON_CHARS = 500
PROFILE_FIELD = "profile_id"  # the optional form field that names the domain profile


class UploadParts(Protocol):
    """A streamed upload form: the file part's bytes as they arrive, then the other fields.

    ``filename`` is known once the file part has started; :meth:`finish` reads the rest of the
    body and raises when the form turns out to be malformed."""

    @property
    def filename(self) -> str | None: ...

    def file_chunks(self) -> Iterator[bytes]: ...

    def finish(self) -> dict[str, str]: ...


def upload_form(wb: Workbench, form: UploadParts) -> DocumentDetail:
    """Spool the form's file part (stopping at the upload limit), read the rest of the form,
    then :func:`ingest` the file with the form's profile. The spool is discarded when the form
    is malformed."""
    spooled = wb.files.spool(form.file_chunks(), max_bytes=wb.settings.ingestion.max_upload_bytes)
    try:
        fields = form.finish()
    except BaseException as exc:
        _discard(wb, spooled, exc)
        raise
    document, dataset = ingest(
        wb,
        spooled=spooled,
        filename=form.filename,
        profile_id=fields.get(PROFILE_FIELD) or None,
    )
    with wb.uow() as uow:
        stored = summary(uow, document)
    return detail(wb, stored, dataset)


def upload(
    wb: Workbench,
    *,
    filename: str | None,
    chunks: Iterable[bytes],
    profile_id: str | None,
    decisions: SchemaDecisions | None = None,
) -> tuple[Document, Dataset | None]:
    """Spool ``chunks`` into the file store (stopping at the upload limit), then :func:`ingest`."""
    spooled = wb.files.spool(chunks, max_bytes=wb.settings.ingestion.max_upload_bytes)
    return ingest(
        wb, spooled=spooled, filename=filename, profile_id=profile_id, decisions=decisions
    )


def ingest(
    wb: Workbench,
    *,
    spooled: SpooledUpload,
    filename: str | None,
    profile_id: str | None,
    decisions: SchemaDecisions | None = None,
) -> tuple[Document, Dataset | None]:
    """Check, store, extract and normalize a spooled upload, and record it.

    ``decisions`` are a reviewer's decisions, laid over the structure the file declares (see
    :func:`~app.normalization.builder.build_dataset`). The spool is discarded (nothing stored)
    when the profile is unknown or the file fails its checks."""
    name = sanitize_filename(filename)
    limits = wb.settings.ingestion
    try:
        profile = _profile(wb, profile_id)
        check = validate_upload(spooled.path, name, limits)
    except BaseException as exc:
        _discard(wb, spooled, exc)
        raise
    stored = wb.files.commit(spooled, media_type=check.media_type)
    document = Document(
        document_id=wb.ids.new(IdPrefix.DOCUMENT),
        original_filename=name,
        format=check.format,
        uploaded_at=wb.clock.now(),
        source_file=stored,
        processing_status=ProcessingStatus.STORED,
        failure_reason=None,
        profile_id=profile.profile_id,
    )
    dataset: Dataset | None = None
    failure: str | None = None
    try:
        raw = wb.adapters.for_format(check.format).extract(
            wb.files.path_for(stored.storage_key), limits
        )
        raw.warnings[:0] = check.warnings
        dataset = build_dataset(
            raw,
            profile=profile,
            document_id=document.document_id,
            ids=wb.ids,
            clock=wb.clock,
            options=wb.settings.normalization,
            decisions=decisions,
        )
        review = dataset.extraction.quality is ExtractionQuality.NEEDS_REVIEW
        status = ProcessingStatus.NEEDS_REVIEW if review else ProcessingStatus.PROCESSED
        document = document.evolve(processing_status=status)
    except WorkbenchError as exc:  # the original stays stored; the reason is shown
        reason = str(exc)[:MAX_FAILURE_REASON_CHARS] or exc.code
        document = document.evolve(processing_status=ProcessingStatus.FAILED, failure_reason=reason)
        failure = exc.code
    with wb.uow() as uow:
        uow.documents.add(document)
        wb.audit(
            uow,
            AuditAction.DOCUMENT_UPLOADED,
            EntityType.DOCUMENT,
            document.document_id,
            f"Uploaded {name} ({document.processing_status.value})",
            after={"sha256": stored.sha256, "size_bytes": stored.size_bytes},
        )
        if dataset is not None:
            uow.datasets.add(dataset)
            wb.audit(
                uow,
                AuditAction.DATASET_CREATED,
                EntityType.DATASET,
                dataset.dataset_id,
                f"Created dataset revision {dataset.revision} for {name}",
                context={"document_id": document.document_id},
            )
    outcome = document.processing_status.value
    logger.info(
        "document %s stored: %s, %d bytes, %s%s",
        document.document_id,
        document.format.value,
        stored.size_bytes,
        outcome,
        f" ({failure})" if failure else "",
        extra={
            "document_id": document.document_id,
            "format": document.format.value,
            "size_bytes": stored.size_bytes,
            "outcome": outcome,
            "error_code": failure,
        },
    )
    return document, dataset


def _discard(wb: Workbench, spooled: SpooledUpload, exc: BaseException) -> None:
    """Delete a rejected upload's spool; nothing of it is stored or logged but its size."""
    wb.files.discard(spooled)
    code = exc.code if isinstance(exc, WorkbenchError) else type(exc).__name__
    logger.info(
        "upload rejected (%s): %d bytes discarded, nothing stored",
        code,
        spooled.size_bytes,
        extra={"error_code": code, "size_bytes": spooled.size_bytes, "outcome": "rejected"},
    )


def _profile(wb: Workbench, profile_id: str | None) -> DomainProfile:
    """The chosen profile; an unknown id is an invalid request (422), not a missing resource."""
    try:
        return wb.profiles.get(profile_id or wb.settings.default_profile_id)
    except NotFoundError as exc:
        available = sorted(profile.profile_id for profile in wb.profiles.list())
        raise InvalidInputError(
            str(exc), details={"profile_id": profile_id, "available": available}
        ) from None


def summary(uow: UnitOfWork, document: Document) -> DocumentSummary:
    """The document with its latest dataset's counts and latest run. Reads the counts stored
    with the dataset and never loads the dataset, so listing large bills stays fast; only
    opening, validating or exporting one document loads its dataset."""
    counts = uow.datasets.latest_counts_for_document(document.document_id)
    run = uow.runs.latest_for_dataset(counts.dataset_id) if counts is not None else None
    return DocumentSummary(
        document_id=document.document_id,
        original_filename=document.original_filename,
        format=document.format,
        uploaded_at=document.uploaded_at,
        processing_status=document.processing_status,
        failure_reason=document.failure_reason,
        profile_id=document.profile_id,
        size_bytes=document.source_file.size_bytes,
        sha256=document.source_file.sha256,
        dataset_id=counts.dataset_id if counts else None,
        table_count=counts.table_count if counts else 0,
        row_count=counts.row_count if counts else 0,
        model=_model_info(document.model),
        last_run=(
            None
            if run is None
            else LastRunSummary(
                run_id=run.run_id,
                status=run.status,
                finished_at=run.finished_at,
                issue_count=run.issue_count,
            )
        ),
    )


def detail(wb: Workbench, document: DocumentSummary, dataset: Dataset | None) -> DocumentDetail:
    """The document summary with its latest dataset's summary."""
    return DocumentDetail(
        document=document,
        dataset=None if dataset is None else datasets.dataset_summary(wb, dataset),
    )


def get(wb: Workbench, document_id: str) -> DocumentDetail:
    with wb.uow() as uow:
        document = uow.documents.get(document_id)
        if document is None:
            raise NotFoundError(f"Unknown document {document_id!r}.")
        found, dataset = summary(uow, document), uow.datasets.latest_for_document(document_id)
    return detail(wb, found, dataset)


def original(wb: Workbench, document_id: str) -> tuple[Path, Document]:
    """Resolve an original by document id, never by a caller-supplied storage path."""
    with wb.uow() as uow:
        document = uow.documents.get(document_id)
        if document is None:
            raise NotFoundError(f"Unknown document {document_id!r}.")
    return wb.files.path_for(document.source_file.storage_key), document


def list_documents(wb: Workbench, *, offset: int, limit: int) -> DocumentPage:
    with wb.uow() as uow:
        page = uow.documents.list(offset=offset, limit=limit)
        items = [summary(uow, document) for document in page.items]
    return DocumentPage(items=items, total=page.total, offset=page.offset, limit=page.limit)


# ---------------------------------------------------------------------- attached model (IFC)
IFC_MEDIA_TYPE = "application/x-step"
_TAKEOFFS: dict[str, ModelTakeoff] = {}  # by sha256; a takeoff never changes for one file
_MAX_CACHED_TAKEOFFS = 8


def attach_model_form(wb: Workbench, document_id: str, form: UploadParts) -> DocumentDetail:
    """Attach the form's IFC file to a document, replacing a model attached before. The file
    must be an IFC STEP file; its takeoff is read now, so a file the takeoff cannot read is
    refused and nothing changes."""
    with wb.uow() as uow:
        if uow.documents.get(document_id) is None:
            raise NotFoundError(f"Unknown document {document_id!r}.")
    spooled = wb.files.spool(form.file_chunks(), max_bytes=wb.settings.ingestion.max_upload_bytes)
    try:
        form.finish()
        name = sanitize_filename(form.filename)
        takeoff = read_takeoff(spooled.path.read_bytes(), filename=name)
    except BaseException as exc:
        _discard(wb, spooled, exc)
        raise
    stored = wb.files.commit(spooled, media_type=IFC_MEDIA_TYPE)
    _remember(takeoff)
    attached = AttachedModel(
        file=stored,
        filename=name,
        schema_name=takeoff.schema,
        project=takeoff.project,
        elements=takeoff.elements,
        unlinked_elements=takeoff.unlinked_elements,
        linked_positions=len(takeoff.positions),
    )
    with wb.uow() as uow:
        document = uow.documents.get(document_id)
        if document is None:
            raise NotFoundError(f"Unknown document {document_id!r}.")
        uow.documents.update(document.evolve(model=attached))
        wb.audit(
            uow,
            AuditAction.MODEL_ATTACHED,
            EntityType.DOCUMENT,
            document_id,
            f"Attached model {name}: {takeoff.elements} elements, "
            f"{len(takeoff.positions)} linked item numbers",
            before=None if document.model is None else {"sha256": document.model.file.sha256},
            after={"sha256": stored.sha256, "size_bytes": stored.size_bytes},
        )
    return get(wb, document_id)


def detach_model(wb: Workbench, document_id: str) -> DocumentDetail:
    """Detach the model; the next validation run no longer compares with it."""
    with wb.uow() as uow:
        document = uow.documents.get(document_id)
        if document is None:
            raise NotFoundError(f"Unknown document {document_id!r}.")
        if document.model is not None:
            uow.documents.update(document.evolve(model=None))
            wb.audit(
                uow,
                AuditAction.MODEL_DETACHED,
                EntityType.DOCUMENT,
                document_id,
                f"Detached model {document.model.filename}",
                before={"sha256": document.model.file.sha256},
            )
    return get(wb, document_id)


def model_takeoff(wb: Workbench, document_id: str) -> ModelTakeoff | None:
    """The takeoff of the model attached to a document, or ``None``."""
    with wb.uow() as uow:
        document = uow.documents.get(document_id)
    if document is None or document.model is None:
        return None
    cached = _TAKEOFFS.get(document.model.file.sha256)
    if cached is not None:
        return cached
    with wb.files.open(document.model.file.storage_key) as handle:
        takeoff = read_takeoff(handle.read(), filename=document.model.filename)
    _remember(takeoff)
    return takeoff


def _remember(takeoff: ModelTakeoff) -> None:
    if len(_TAKEOFFS) >= _MAX_CACHED_TAKEOFFS:
        _TAKEOFFS.pop(next(iter(_TAKEOFFS)))
    _TAKEOFFS[takeoff.sha256] = takeoff


def _model_info(model: AttachedModel | None) -> ModelInfo | None:
    if model is None:
        return None
    return ModelInfo(
        filename=model.filename,
        sha256=model.file.sha256,
        size_bytes=model.file.size_bytes,
        schema_name=model.schema_name,
        project=model.project,
        elements=model.elements,
        unlinked_elements=model.unlinked_elements,
        linked_positions=model.linked_positions,
    )
