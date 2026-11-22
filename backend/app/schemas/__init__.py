"""The API's data contract: Pydantic models of every response (``docs/api/rest-api.md``).

Services build these models and the routers declare them as response models, so
``/openapi.json`` describes every response. Canonical records (``app.models``) appear in them
unchanged: a run, an issue, a row or a column is serialized exactly as its model defines it.
Request bodies stay next to their routes (``app.api.routes``).
"""
