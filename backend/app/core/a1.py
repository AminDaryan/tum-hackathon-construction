"""Spreadsheet A1-notation helpers (kept dependency-free on purpose)."""

from __future__ import annotations


def column_letter(column_number: int) -> str:
    """Convert a 1-based column number to letters: 1 -> A, 27 -> AA."""
    if column_number < 1:
        raise ValueError("column_number must be >= 1")
    letters = []
    n = column_number
    while n:
        n, remainder = divmod(n - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


def a1_reference(row_number: int, column_number: int) -> str:
    """Return an A1 reference such as ``C12`` for 1-based row and column numbers."""
    if row_number < 1:
        raise ValueError("row_number must be >= 1")
    return f"{column_letter(column_number)}{row_number}"
