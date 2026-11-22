"""Tabular Integrity Workbench backend.

Layers (outer layers depend on inner ones, never the reverse):

* ``app.models``          canonical, format-agnostic domain model (documents, datasets, issues)
* ``app.validation``      detector contract, registry, pipeline and the detectors themselves
* ``app.ingestion``       format adapters that turn uploaded files into raw cell grids
* ``app.normalization``   turns raw grids into the canonical dataset model
* ``app.repositories``    persistence behind small protocols (SQLite today, PostgreSQL-ready)
* ``app.services``        use cases that orchestrate the layers above
* ``app.api``             FastAPI transport layer (REST, error envelopes, dependency wiring)
"""

__version__ = "0.1.0"
