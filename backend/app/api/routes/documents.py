"""Documents: upload (streamed straight into the file store), list, detail."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.api.multipart import UploadForm, body_from_event_loop
from app.api.routes._deps import Offset, content_disposition, workbench
from app.schemas.documents import DocumentDetail, DocumentPage
from app.services import documents, runs

router = APIRouter(tags=["documents"])
UPLOAD_PATH = "/documents"
_UPLOAD_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        "profile_id": {"type": "string"},
                    },
                }
            }
        },
    }
}


@router.post(UPLOAD_PATH, status_code=201, openapi_extra=_UPLOAD_BODY)
async def upload_document(request: Request) -> DocumentDetail:
    """``multipart/form-data`` with ``file`` and an optional ``profile_id``. The body is parsed
    while it arrives (``app.api.multipart``); the service stores the file part as it streams
    in and does the rest of the work in a worker thread."""
    form = UploadForm(request.headers.get("content-type"), body_from_event_loop(request.stream()))
    uploaded = await run_in_threadpool(documents.upload_form, workbench(request), form)
    if uploaded.dataset is not None:  # every bill is validated without being asked
        runs.check_soon(workbench(request), uploaded.dataset.dataset_id)
    return uploaded


_MODEL_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}


@router.put("/documents/{document_id}/model", openapi_extra=_MODEL_BODY)
async def attach_model(request: Request, document_id: str) -> DocumentDetail:
    """Attach a model (IFC, ``multipart/form-data`` with ``file``) to a bill, replacing one
    attached before. Its elements link to bill positions by classification references whose
    identification is the item number; the next validation run compares their quantities."""
    form = UploadForm(request.headers.get("content-type"), body_from_event_loop(request.stream()))
    attached = await run_in_threadpool(
        documents.attach_model_form, workbench(request), document_id, form
    )
    if attached.dataset is not None:  # the model changes what the checks compare with
        runs.check_soon(workbench(request), attached.dataset.dataset_id)
    return attached


@router.delete("/documents/{document_id}/model")
def detach_model(request: Request, document_id: str) -> DocumentDetail:
    detached = documents.detach_model(workbench(request), document_id)
    if detached.dataset is not None:
        runs.check_soon(workbench(request), detached.dataset.dataset_id)
    return detached


@router.get("/documents")
def list_documents(
    request: Request,
    offset: Offset = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> DocumentPage:
    return documents.list_documents(workbench(request), offset=offset, limit=limit)


@router.get("/documents/{document_id}")
def get_document(request: Request, document_id: str) -> DocumentDetail:
    return documents.get(workbench(request), document_id)


@router.get(
    "/documents/{document_id}/original",
    response_class=FileResponse,
    responses={
        200: {
            "description": "Unmodified original upload (attachment).",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
def get_original(request: Request, document_id: str) -> FileResponse:
    """Original bytes under the same authentication as document metadata; no public asset copy."""
    path, document = documents.original(workbench(request), document_id)
    return FileResponse(
        path,
        media_type=document.source_file.media_type,
        headers={
            "Content-Disposition": content_disposition(document.original_filename),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
