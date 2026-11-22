"""PDF import: printed bills of quantities read from a PDF's text layer.

``layout`` (PDFium: positioned words and lines) -> ``bill`` (the bill's columns, items,
categories and sums -> the bill model shared with GAEB) -> ``adapter`` (the ingestion adapter;
the table is built by :mod:`app.ingestion.gaeb.flatten`).
"""
