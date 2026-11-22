"""How far a price lies from the prices it is compared with, as a band of the finding.

Two price checks flag far more than they find. On the practice benchmark P1 (8 faulty bills and
their 4 clean originals, the checks of 21 Nov 2026) the size of the deviation separated their
real faults from their false alarms:

* ``statistical.peer_price/peer_price_outlier``: of 32 findings whose price is less than
  eight times off the median of its peers, none was on a planted fault; of 36 at eight times or
  more, 9 were.
* ``statistical.rate_consistency/identical_positions_price_differs`` on two positions: of 28
  findings whose prices are less than three times apart, 2 were on a planted fault (one of them
  flagged by another check as well); of 4 at three times or more, or exactly 19 % VAT apart,
  all 4 were.

The same bands on the model's price claims (the numbers of the related position it names) were
left out: in the fresh model run of 21 Nov (p1-haiku-v2) they would have taken one position, on
a clean bill, off the list.

A band does not drop a finding by itself. The reading list (:mod:`app.evaluation.reading_list`)
learns each rule's hit rate on other bills and keeps a rule only above a cut; with the band in
the rule's key (:func:`with_band`) a weak band falls under that cut by measurement. The
thresholds were chosen while looking at P1, so the held-out benchmark B8 is the honest test of
them.

The band is read from the finding's title, the one place a finding carries both prices. The
titles are written by the two checks; the tests run the checks, so a changed wording fails there
instead of silently dropping the band. A finding whose title gives no two prices (a group of
three or more identical positions) has no band and keeps its rule's own key.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.evaluation.scoring import Finding

PEER_PRICE = ("statistical.peer_price", "peer_price_outlier")
IDENTICAL_PRICES = ("statistical.rate_consistency", "identical_positions_price_differs")

# A slipped decimal point makes a price ten times too high or too low; eight leaves room for a
# peer median that is not exactly the right price.
TENFOLD = Decimal(8)
# Identical work priced three times apart is seldom a pricing choice.
FAR_APART = Decimal(3)
# A net price copied as a gross one is 19 % (German VAT) higher, to the cent.
VAT = Decimal("1.19")
CENT = Decimal("0.01")

_NUMBER = r"-?\d+(?:\.\d+)?"
# statistical.peer_price: "Unit price 8.00 far below comparable positions (median 81.00)"
_PEER_TITLE = re.compile(
    rf"^Unit price (?P<a>{_NUMBER}) far (?:above|below) comparable positions "
    rf"\(median (?P<b>{_NUMBER})\)"
)
# statistical.rate_consistency, two identical positions: "Identical positions priced 45.80 and
# 458.00" (a group of three or more names no prices in its title)
_PAIR_TITLE = re.compile(rf"^Identical positions priced (?P<a>{_NUMBER}) and (?P<b>{_NUMBER})$")


def with_band(key: str, band: str | None) -> str:
    """A rule's hit-rate key with the finding's band, when it has one."""
    return key if band is None else f"{key}#{band}"


def finding_band(finding: Finding) -> str | None:
    """The band of a price check's finding, ``None`` for every other rule or when its title
    gives no two prices.

    * peer price: ``tenfold`` when the price is at least :data:`TENFOLD` times above or below the
      median of its peers, else ``below_tenfold``;
    * two identical positions: ``far_apart`` when their unit prices are at least
      :data:`FAR_APART` times apart or exactly :data:`VAT` apart, else ``close``.
    """
    rule = (finding.detector_id, finding.rule_id)
    if rule == PEER_PRICE:
        prices = _prices(_PEER_TITLE, finding.title)
        if prices is None:
            return None
        low, high = prices
        return "tenfold" if high / low >= TENFOLD else "below_tenfold"
    if rule == IDENTICAL_PRICES:
        prices = _prices(_PAIR_TITLE, finding.title)
        if prices is None:
            return None
        low, high = prices
        return "far_apart" if high / low >= FAR_APART or abs(high - low * VAT) <= CENT else "close"
    return None


def _prices(title: re.Pattern[str], text: str) -> tuple[Decimal, Decimal] | None:
    """The two prices the title names, lowest first; ``None`` when it names none, or one that is
    zero or negative."""
    match = title.match(text)
    if match is None:
        return None
    a, b = Decimal(match["a"]), Decimal(match["b"])
    if a <= 0 or b <= 0:
        return None
    return min(a, b), max(a, b)
