"""Ingestion: format adapters that turn uploaded files into raw cell grids.

* ``base``: raw types (:class:`~app.ingestion.base.RawWorkbook`, ``RawSheet``, ``RawCell``) and
  the :class:`~app.ingestion.base.IngestionAdapter` protocol.
* ``security``: checks that run before any parser touches an upload (file name, format
  sniffing, ZIP container) and the limit guard adapters use while extracting.
* ``csv_adapter`` (stdlib ``csv``) and ``xlsx_adapter`` (openpyxl): the built-in adapters.
* ``registry``: selects the adapter for a detected format.

Nothing is re-exported here, so importing ``app.ingestion.base`` does not import openpyxl.
"""
