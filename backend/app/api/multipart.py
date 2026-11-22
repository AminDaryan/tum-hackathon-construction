"""Streaming ``multipart/form-data`` for the upload route (``docs/api/rest-api.md``, "Security of
the local API": uploads are streamed into the file store).

Starlette's form parser copies every file part into a temporary file of its own before the route
runs. Here the body is parsed while it arrives, and the bytes of the ``file`` part go straight to
:meth:`FileStore.spool`, which counts, hashes and writes them (and stops at the upload limit).
Text fields such as ``profile_id`` are kept in memory, at most :data:`MAX_FIELD_BYTES` each and
:data:`MAX_PARTS` parts per request; they may come before or after the file. Exactly one file
part, named ``file``, is accepted. The parsing itself is :mod:`python_multipart` (the parser
Starlette uses); this module reads part headers and routes the bytes.

:class:`UploadForm` is synchronous: the route runs it in a worker thread and gives it the request
body through :func:`body_from_event_loop`, which awaits each chunk on the event loop. Errors raised
while receiving (the body limit, a client disconnect) therefore surface inside the thread, where
:meth:`FileStore.spool` deletes the partial file.
"""

from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING

import anyio.from_thread
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header

from app.core.errors import InvalidInputError

if TYPE_CHECKING:
    from python_multipart.multipart import MultipartCallbacks  # defined for type checkers only

MAX_FIELD_BYTES = 1024
MAX_PARTS = 16


class MalformedUploadError(InvalidInputError):
    """The body is not a usable ``multipart/form-data`` upload (``422``)."""

    code = "request_validation_failed"


def body_from_event_loop(stream: AsyncIterator[bytes]) -> Iterator[bytes]:
    """The request body for a worker thread: each chunk is awaited on the event loop."""

    async def next_chunk() -> bytes | None:
        try:
            return await stream.__anext__()
        except StopAsyncIteration:
            return None

    while (chunk := anyio.from_thread.run(next_chunk)) is not None:
        if chunk:
            yield chunk


class UploadForm:
    """One multipart body: text fields and a single file part named ``file_field``.

    Call :meth:`file_chunks` first (it yields the file's bytes as they arrive; fields that came
    before the file are already in :attr:`fields`, and :attr:`filename` is set), then
    :meth:`finish` to read the rest of the body.
    """

    def __init__(
        self, content_type: str | None, body: Iterator[bytes], *, file_field: str = "file"
    ) -> None:
        media_type, params = parse_options_header(content_type or "")
        boundary = params.get(b"boundary")
        if media_type != b"multipart/form-data" or not boundary:
            raise MalformedUploadError(
                "The upload must be a multipart/form-data request with a 'file' part.",
                details={"content_type": content_type},
            )
        self.file_field = file_field
        self.fields: dict[str, str] = {}
        self.filename: str | None = None
        self._body = body
        self._parts = 0
        self._header_name = bytearray()
        self._header_value = bytearray()
        self._headers: dict[bytes, bytes] = {}
        self._field: str | None = None  # the text field being read
        self._value = bytearray()
        self._in_file = False
        self._file_started = False
        self._file_ended = False
        self._file_data: deque[bytes] = deque()
        self._ended = False
        self._finalized = False
        callbacks: MultipartCallbacks = {
            "on_part_begin": self._on_part_begin,
            "on_header_field": self._on_header_field,
            "on_header_value": self._on_header_value,
            "on_header_end": self._on_header_end,
            "on_headers_finished": self._on_headers_finished,
            "on_part_data": self._on_part_data,
            "on_part_end": self._on_part_end,
            "on_end": self._on_end,
        }
        self._parser = MultipartParser(boundary, callbacks)

    def file_chunks(self) -> Iterator[bytes]:
        """The file part's bytes, in order, as the body arrives."""
        while True:
            while self._file_data:
                yield self._file_data.popleft()
            if self._file_ended:
                return
            if not self._feed():
                break
        if self._file_started:
            raise MalformedUploadError("The upload ended before the file was complete.")
        raise MalformedUploadError(f"The request has no file part named {self.file_field!r}.")

    def finish(self) -> dict[str, str]:
        """Read the rest of the body; return all text fields."""
        while self._feed():
            pass
        if not self._ended:
            raise MalformedUploadError("The multipart body ended early.")
        return self.fields

    def _feed(self) -> bool:
        chunk = next(self._body, None)
        try:
            if chunk is None:
                if not self._finalized:
                    self._finalized = True
                    self._parser.finalize()
                return False
            self._parser.write(chunk)
        except MultipartParseError as exc:
            raise MalformedUploadError(f"The multipart body is malformed: {exc}") from None
        return True

    # python_multipart callbacks ---------------------------------------------------------------

    def _on_part_begin(self) -> None:
        self._parts += 1
        if self._parts > MAX_PARTS:
            raise MalformedUploadError(f"The upload has more than {MAX_PARTS} parts.")
        self._headers = {}

    def _on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name += data[start:end]

    def _on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]

    def _on_header_end(self) -> None:
        self._headers[bytes(self._header_name).lower()] = bytes(self._header_value)
        self._header_name.clear()
        self._header_value.clear()

    def _on_headers_finished(self) -> None:
        disposition, options = parse_options_header(self._headers.get(b"content-disposition", b""))
        raw_name = options.get(b"name")
        if disposition != b"form-data" or raw_name is None:
            raise MalformedUploadError("A multipart part has no form-data name.")
        name = raw_name.decode("utf-8", errors="replace")
        raw_filename = options.get(b"filename")
        if name == self.file_field:
            if self._file_started:
                raise MalformedUploadError("Only one file can be uploaded per request.")
            self._file_started = self._in_file = True
            if raw_filename is not None:
                self.filename = raw_filename.decode("utf-8", errors="replace")
        elif raw_filename is not None:
            raise MalformedUploadError(
                f"Unexpected file part {name!r}; send the file as {self.file_field!r}."
            )
        else:
            self._field = name
            self._value.clear()

    def _on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._in_file:
            self._file_data.append(data[start:end])
            return
        self._value += data[start:end]
        if len(self._value) > MAX_FIELD_BYTES:
            raise MalformedUploadError(
                f"Form field {self._field!r} is longer than {MAX_FIELD_BYTES} bytes."
            )

    def _on_part_end(self) -> None:
        if self._in_file:
            self._in_file = False
            self._file_ended = True
        elif self._field is not None:
            try:
                self.fields[self._field] = self._value.decode("utf-8")
            except UnicodeDecodeError:
                raise MalformedUploadError(
                    f"Form field {self._field!r} is not UTF-8 text."
                ) from None
            self._field = None

    def _on_end(self) -> None:
        self._ended = True
