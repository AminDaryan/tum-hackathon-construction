"""GAEB DA XML import: everything the workbench knows about GAEB lives in this package.

``schemas`` (supported versions and phases, official XSDs) -> ``reader`` (safe parse, identity
and schema checks -> ``model.GaebDocument``) -> ``flatten`` (table plus declared structure) ->
``adapter`` (the ingestion adapter). The rest of the system only sees the raw table.
"""
