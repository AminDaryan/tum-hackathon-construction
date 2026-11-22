"""The bid risk report as a PDF (issue #112): the bills, the ranked rows with both kinds of money,
the reminders about several positions and the notes, read back from the file; the same report
gives the same bytes."""

from __future__ import annotations

import io

import pypdfium2 as pdfium

from app.models.issue import Severity
from app.risk.bid_report_pdf import render
from app.risk.models import Money, MoneyKind, SizeClass
from tests.unit.risk.test_bid_report import _bill, _exact, _part, _pos, _report, _risk


def pdf_text(data: bytes) -> str:
    document = pdfium.PdfDocument(io.BytesIO(data))
    try:
        return "\n".join(page.get_textpage().get_text_range() for page in document)
    finally:
        document.close()


def _flat(data: bytes) -> str:
    return " ".join(pdf_text(data).split())


def test_the_pdf_lists_the_rows_their_money_and_the_reminders_apart() -> None:
    a, b, c, d = _pos("A", "5000"), _pos("B", "3000"), _pos("C", "1000"), _pos("D", "500")
    e = _pos("E", "200")
    report = _report(
        _part(
            "lv",
            _bill(a, b, c, d, e),
            _risk("wide", Severity.HIGH, a, b, c, d),
            _risk("high", Severity.HIGH, c),
            _risk("exact", Severity.MEDIUM, d, money=_exact("400")),
            _risk("also", Severity.MEDIUM, d),
        ),
        limit=3,
    )
    data = render(report)
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
    text = _flat(data)
    assert "Bid risk report: Tender" in text
    assert "lv.x83: 5 positions, total 9,700.00 EUR." in text
    assert "2 of 2 positions with reminders; 1 more listed for their size." in text
    # C, then D with its two reminders (the rank on both rows), then A for its size.
    assert text.index("1 C") < text.index("2 D") < text.index("3 A")
    assert "1,000.00 EUR 10.3 % of the bill" in text
    assert "Reminder exact" in text and "400.00 EUR" in text
    assert "Reminder also" in text and "Not known" in text
    assert "No reminder: listed for its size" in text
    assert "Reminders about several positions" in text
    assert "Concerns 4 positions: A, B, C, D" in text
    assert "How this list was made" in text and report.notes[0][:40] in text
    assert render(report) == data


def test_a_large_share_is_said_only_of_several_positions_together() -> None:
    # The reminder's size class is the share of all its positions: under the row of a small
    # position it read as that position's size ("a large share" for 0.1 % of the bill).
    large = Money(kind=MoneyKind.UNKNOWN, basis="No amount.", size_class=SizeClass.LARGE)
    a, b, c, d = _pos("A", "5000"), _pos("B", "3000"), _pos("C", "1000"), _pos("D", "10")
    report = _report(
        _part(
            "lv",
            _bill(a, b, c, d),
            _risk("pair", Severity.HIGH, a, d, money=large),
            _risk("wide", Severity.HIGH, a, b, c, d, money=large),
        )
    )
    text = _flat(render(report))
    assert text.count("The positions concerned are a large share of the bill") == 1
    assert text.index("large share") > text.index("Reminders about several positions")


def test_an_unpriced_bill_says_so_and_a_report_without_rows_still_renders() -> None:
    p1 = _pos("01")
    text = _flat(render(_report(_part("lv", _bill(p1), _risk("one", Severity.MEDIUM, p1)))))
    assert "lv.x83: 1 position, no prices." in text
    assert "01 Position 01" in text and "No price" in text
    assert "lv.x83 has no prices" in text

    empty = _flat(render(_report(_part("lv", _bill(p1)))))
    assert "0 of 0 positions with reminders." in empty
    assert "Page 1 of 1" in empty
