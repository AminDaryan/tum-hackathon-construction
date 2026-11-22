"""Prices of a bid that can exclude it or cannot cover cost: the price completeness of plan
section 8 (B2.1) and the bid prices of plan section 5a, in one check.

GAEB 3.3 §4.6.4 separates a missing price, a position marked "nicht angeboten" and an explicit
0,00. Seven rules, finding category in brackets (``app.models.finding_category`` holds the
table). They read the item frame (:func:`app.validation.support.items.item_frame`) and apply to
tables where at least one item row is in a price state of a bid: a unit price (0,00 included),
a ``not_offered`` marker in the unit price, or an item type that says "nicht angeboten". A table
whose unit price is empty on every item row is an unpriced bill (a tender, X81 or X83) and is
not checked; when no table is priced the check is not applicable and says so once. A bid whose
positions are mostly not offered is still checked: those positions are what it reports.

* ``not_offered`` [error]: the GAEB item type says "nicht angeboten" (only a bid carries it),
  or the unit price holds the value marker ``not_offered`` (a spreadsheet's "nicht angeboten"
  or "not offered"): the bidder left the price out. Confirmed rule violation, high; medium on a
  position declared outside the sum (it adds nothing to the total, but GAEB 3.3 §4.5.2 asks
  for a price for the base and every alternative execution). In a file whose extraction
  warnings include one of ``undetermined_count_warnings`` (a GAEB X84 or D84 bid, which does not
  say which positions count), the finding adds ``undetermined_count_note``. The ``boq`` profile
  exempts these rows from ``deterministic.required_values``, so the missing price is one
  finding, here, and the marker contributes zero to the totals.
* ``zero_price`` [error]: a unit price of 0,00 on a position whose quantity is not 0: the work
  is offered free of charge, or its price was left out. Suspected anomaly, medium.
* ``token_price`` [error]: a unit price equal to one of ``token_prices`` (``boq``: 0,01), a
  known sign of costs shifted into other positions (Mischkalkulation, BGH X ZB 7/04), which can
  exclude a bid. Suspected anomaly, medium.
* ``price_below_floor`` [risk]: an hourly labour rate below the statutory minimum wage (the
  unit is an hour and the item type says "Stundenlohnarbeiten" or the text names labour; an
  hour unit alone is not enough, as some bills write "Std" for piece x day). Suspected
  anomaly, high. A rate that ``zero_price`` or ``token_price`` reports is not reported again.
  No floor is set for other units: there is no defensible source for one.
* ``discount_exceeds_price`` [error]: an item discount above 100%, whether written as a
  number or with a percent sign, reverses the price instead of reducing it: medium,
  suspected anomaly. Exactly 100% and negative discounts (signed surcharges) are allowed.
* ``negative_price`` [error]: a unit price below zero on a position whose texts do not call it
  a credit or deduction (``credit_pattern``: Gutschrift, Rückvergütung, Erlös, Abzug,
  Minderkosten, Nachlass, ...): the bidder would pay the client for the work, so the sign is
  wrong or a credit is not declared. The line total can still multiply correctly, which is why
  the arithmetic checks stay silent. Suspected anomaly, high.
* ``tax_in_unit_price`` [error]: a unit price that is not a whole cent amount and is exactly a
  whole cent amount plus one of ``vat_rates`` (``boq``: 19 %): a gross price in a bill of net
  prices, such as 9,996 for 8,40 net. Suspected anomaly, medium. A gross price rounded to
  cents cannot be told from a net price and is not reported.

``zero_price``, ``token_price``, ``negative_price`` and ``tax_in_unit_price`` skip positions
whose item type says "entfällt" or "nicht angeboten", but not positions outside the sum: an
alternative or contingency position must be priced too (GAEB 3.3 §4.5.2). Amounts stay
``Decimal``; an excessive discount is reported separately from the price itself.
"""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from pydantic import Field, field_validator, model_validator

from app.models.dataset import CellRef, Table
from app.models.issue import EvidenceClass, EvidenceItem, EvidenceKind, Severity, ValidationIssue
from app.models.values import DataType, ValueMarker
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.detector import (
    Applicability,
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
    plannable,
)
from app.validation.deterministic._reference_support import checked_pattern, clip
from app.validation.deterministic._support import FieldId, fmt
from app.validation.domain.boq._clause_support import (
    HOUR_UNIT_IDS,
    HOURLY_ITEM_TYPE_PATTERN,
    LABOUR_PATTERN,
    is_hourly_labour,
    search_text,
)
from app.validation.support.items import ItemFields, ItemRecord, item_frame

RULE_ZERO = "zero_price"
RULE_NOMINAL = "token_price"
RULE_NOT_OFFERED = "not_offered"
RULE_FLOOR = "price_below_floor"
RULE_DISCOUNT = "discount_exceeds_price"
RULE_NEGATIVE = "negative_price"
RULE_TAX = "tax_in_unit_price"
CATEGORY_PRICE = "price"
CATEGORY_COMPLETENESS = "completeness"

PRICED_TABLES = "priced_tables"
UNPRICED_TABLES = "tables_not_priced"
OTHER_CURRENCY = "rates_in_another_currency"

TOKEN_PRICES = (Decimal("0.01"),)
EXCLUDED_ITEM_TYPE_PATTERN = r"\bentfällt\b|\bnicht\s+angeboten\b"
NOT_OFFERED_PATTERN = r"\bnicht\s+angeboten\b"
# Words of a position that is a credit or deduction on purpose, so its price may be negative.
CREDIT_PATTERN = (
    r"\b(?:gutschrift\w*|rückvergütung\w*|rückerstattung\w*|\w*erlös\w*|abzug|abzüge|abzüglich"
    r"|minder(?:kosten|preis\w*|ung\w*|vergütung\w*)|nachlass\w*|rabatt\w*|skonto)\b"
)
# Value added tax rates in Germany, in percent (§ 12 (1) UStG: 19 %). The reduced rate of 7 %
# does not apply to construction work and is left out.
VAT_RATES = (Decimal("19"),)
_CENT = Decimal("0.01")
# Statutory minimum wage in Germany (Mindestlohngesetz, MiLoG), gross per hour, since 2026-01-01.
MINIMUM_WAGE = Decimal("13.90")
MINIMUM_WAGE_SOURCE = "statutory minimum wage (MiLoG), 13,90 EUR gross per hour since 2026-01-01"

# Plan 5a: a recommendation never tells the bidder to change the client's bill or to carry a
# position's cost in other positions (Mischkalkulation, BGH X ZB 7/04).
_OWN_COST = (
    "Before submission, enter the price that covers this position's own cost, never priced "
    "into other positions (BGH, X ZB 7/04). If the bill itself says the work is included in "
    "another position, ask a bidder question instead of writing a note into the bill."
)
ZERO_RECOMMENDATION = (
    "Confirm this price: a unit price of 0,00 offers the work free of charge, or its price was "
    "left out. " + _OWN_COST
)
NOMINAL_RECOMMENDATION = (
    "Check this price: a token unit price suggests the cost sits in other positions, which can "
    "exclude the bid. " + _OWN_COST
)
NOT_OFFERED_RECOMMENDATION = (
    "Enter a price before submission, or confirm that the tender allows leaving this position "
    "out: missing prices can exclude the bid (§ 16a (2) VOB/A)."
)
# Filled in with the configured floor and currency, so a changed floor changes the text too.
NEGATIVE_RECOMMENDATION = (
    "Check the sign of this price before submission. If the position is a credit to the "
    "client, say so in its text; otherwise enter the positive price."
)
TAX_RECOMMENDATION = (
    "Enter the net unit price before submission: the unit prices of a bill are net, and the "
    "value added tax is added once, to the total."
)
FLOOR_RECOMMENDATION = (
    "An hourly rate below {floor} {currency} cannot cover the wage, let alone social costs and "
    "overheads. Check the rate before submission; an unusually low price must be explained on "
    "request and can lead to exclusion."
)


class BoqBidPricesConfig(DetectorConfig):
    code_field: FieldId = plannable("item_code", description="Field holding the position number.")
    unit_price_field: FieldId = plannable("unit_price", description="Field holding the unit price.")
    item_type_field: FieldId = plannable(
        "item_type", description="Field holding the item type (GAEB Positionsart)."
    )
    token_prices: tuple[Decimal, ...] = Field(
        default=TOKEN_PRICES,
        min_length=1,
        description="Unit prices that stand for no price (token_price); 0,00 is zero_price.",
    )
    excluded_item_type_pattern: str = Field(
        default=EXCLUDED_ITEM_TYPE_PATTERN,
        description="Item types whose zero or token price is no finding (entfällt, nicht "
        "angeboten).",
    )
    not_offered_pattern: str = Field(
        default=NOT_OFFERED_PATTERN, description="Item types of a position not offered."
    )
    undetermined_count_warnings: list[str] = Field(
        default_factory=list,
        description="Extraction warning codes of a file that does not say which positions "
        "count toward the totals (a GAEB X84 or D84 bid).",
    )
    undetermined_count_note: str = Field(
        default="",
        description="What a not_offered finding in such a file says about counting.",
    )
    hourly_wage_floor: Decimal = Field(
        default=MINIMUM_WAGE,
        gt=0,
        description=(
            "Lowest hourly labour rate, in floor_currency: the statutory minimum wage in "
            "Germany (Mindestlohngesetz), 13.90 EUR gross per hour since 2026-01-01. Update it "
            "each January."
        ),
    )
    floor_currency: str = Field(
        default="EUR", pattern=r"^[A-Z]{3}$", description="Currency of the hourly wage floor."
    )
    floor_source: str = Field(
        default=MINIMUM_WAGE_SOURCE, min_length=1, description="Source of the floor, as shown."
    )
    hourly_item_type_pattern: str = Field(
        default=HOURLY_ITEM_TYPE_PATTERN, description="Item types of hourly work."
    )
    hour_unit_ids: tuple[str, ...] = Field(
        default=HOUR_UNIT_IDS, description="Unit ids (of the unit catalogue) of an hour."
    )
    labour_pattern: str = Field(
        default=LABOUR_PATTERN,
        description="Words that make a position in hours hourly labour (Facharbeiter, Helfer).",
    )
    credit_pattern: str = Field(
        default=CREDIT_PATTERN,
        description="Words of a position that is a credit or deduction on purpose (Gutschrift, "
        "Abzug, Nachlass): its negative unit price is no finding.",
    )
    vat_rates: tuple[Decimal, ...] = Field(
        default=VAT_RATES,
        description="Value added tax rates in percent that tax_in_unit_price looks for in a "
        "unit price (Germany: 19).",
    )

    @field_validator(
        "excluded_item_type_pattern",
        "not_offered_pattern",
        "hourly_item_type_pattern",
        "labour_pattern",
        "credit_pattern",
    )
    @classmethod
    def _valid_pattern(cls, value: str) -> str:
        return checked_pattern(value, groups=None)

    @field_validator("vat_rates")
    @classmethod
    def _positive_rates(cls, value: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
        if any(rate <= 0 or rate >= 100 for rate in value):
            raise ValueError("vat_rates are percentages above 0 and below 100")
        return value

    @model_validator(mode="after")
    def _note_for_warnings(self) -> BoqBidPricesConfig:
        if self.undetermined_count_warnings and not self.undetermined_count_note.strip():
            raise ValueError("undetermined_count_warnings need an undetermined_count_note")
        return self


class BoqBidPricesDetector(Detector[BoqBidPricesConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="domain.boq_bid_prices",
        name="Bid prices (positions not offered, zero, token and negative prices, hourly rates)",
        version="1.4.0",
        category=DetectorCategory.DOMAIN,
        description=(
            "Checks the unit prices of a priced bill or bid before submission: positions marked "
            "'nicht angeboten', unit prices of 0,00 on a position with a quantity, token prices "
            "(such as 0,01) that suggest costs moved into other positions, and hourly labour "
            "rates below the statutory minimum wage; also item discounts exceeding 100%, unit "
            "prices below zero, and unit prices that carry value added tax."
        ),
        required_fields=("unit_price",),
        optional_fields=(
            "item_type",
            "item_code",
            "unit",
            "description",
            "long_description",
            "discount_percent",
        ),
        supported_data_types=(DataType.NUMBER, DataType.TEXT),
        applicability=(
            "Tables with a unit price, or a position marked not offered, on at least one item row "
            "(a priced bill or bid)."
        ),
        evidence_classes=(
            EvidenceClass.SUSPECTED_ANOMALY,
            EvidenceClass.CONFIRMED_RULE_VIOLATION,
        ),
        issue_categories=(CATEGORY_PRICE, CATEGORY_COMPLETENESS),
        limitations=(
            "The hourly floor is the German statutory minimum wage of the date in its "
            "description; a collective agreement for the trade may set a higher wage.",
            "Hourly labour is recognised by an hour unit with the item type "
            "Stundenlohnarbeiten or a text that names labour; other low prices are left to the "
            "comparison checks.",
            "A table whose unit price is empty on every item row (a tender) is not checked.",
            "In a GAEB X84 or D84 bid, whether a position counts toward the total is stated in "
            "the tender it answers, not in the bid.",
            "A negative price is not reported when the position's text calls it a credit or "
            "deduction; whether that credit is intended is not checked.",
            "Value added tax in a unit price shows only while the price is not rounded to "
            "cents; a gross price rounded to cents looks like a net price.",
        ),
        references=(
            "GAEB DA XML 3.3, §4.6.4 (missing price, not offered, 0,00) and §4.5.2 (the base "
            "and every alternative execution are offered)",
            "BGH, decision of 18 May 2004, X ZB 7/04 (no costs moved into other positions)",
            "VOB/A 2019 § 16a (2) (missing prices)",
            "Mindestlohngesetz (MiLoG), minimum wage of 13,90 EUR since 2026-01-01",
            "Umsatzsteuergesetz (UStG) § 12 (1): value added tax of 19 %",
        ),
        cost="low",
    )
    config_model = BoqBidPricesConfig

    def required_fields(self, config: BoqBidPricesConfig) -> tuple[str, ...]:
        return (config.unit_price_field,)

    def applicability(
        self, context: ValidationContext, config: BoqBidPricesConfig
    ) -> Applicability:
        priced = [t for t in self._tables(context, config) if t[1]]
        if not priced:
            return Applicability.no(
                "No table has a unit price on any item row (an unpriced bill, such as a tender)."
            )
        return Applicability.yes(f"Priced item rows in: {', '.join(t.name for t, _ in priced)}.")

    def validate(self, context: ValidationContext, config: BoqBidPricesConfig) -> DetectorResult:
        result = DetectorResult()
        frame = item_frame(context, self._fields(config))
        tables = {t.table_id: t for t, priced in self._tables(context, config) if priced}
        result.count(PRICED_TABLES, len(tables))
        result.count(UNPRICED_TABLES, len(self._tables(context, config)) - len(tables))
        for record in frame.records:
            table = tables.get(record.table_id)
            if table is None:
                continue
            context.checkpoint()
            marker = context.marker(table, table.row(record.row_id), config.unit_price_field)
            by_type = self._by_type(config, record)
            if by_type or marker is ValueMarker.NOT_OFFERED:
                result.add(self._not_offered(context, config, table, record, by_type=by_type))
            elif self._is_zero(config, record):
                result.add(self._token(context, config, table, record, rule_id=RULE_ZERO))
            elif self._is_token(config, record):
                result.add(self._token(context, config, table, record, rule_id=RULE_NOMINAL))
            elif self._is_negative(config, record):
                result.add(self._negative(context, config, table, record))
            elif self._below_floor(context, config, table, record, result):
                result.add(self._floor(context, config, table, record))
            elif (taxed := self._with_tax(config, record)) is not None:
                result.add(self._tax(context, config, table, record, *taxed))
            if record.discount_percent is not None and record.discount_percent > 100:
                result.add(self._discount(context, table, record))
        return result

    # ------------------------------------------------------------------ selection
    def _fields(self, config: BoqBidPricesConfig) -> ItemFields:
        return ItemFields(
            item_code=config.code_field,
            unit_price=config.unit_price_field,
            item_type=config.item_type_field,
        )

    def _tables(
        self, context: ValidationContext, config: BoqBidPricesConfig
    ) -> list[tuple[Table, bool]]:
        """Every table of the item frame and whether it is priced: at least one item row has a
        unit price, a ``not_offered`` marker in it, or an item type that says "nicht angeboten"
        (GAEB 3.3 §4.6.4: all three are price states of a bid). Rows not offered or omitted are
        not held against the table, so a bid that offers few of its positions is checked."""
        frame = item_frame(context, self._fields(config))
        tables = {table.table_id: table for table in context.tables()}
        priced: dict[str, bool] = {}
        for record in frame.records:
            table = tables.get(record.table_id)
            if table is None or priced.get(record.table_id):
                continue
            priced[record.table_id] = self._in_price_state(context, config, table, record)
        return [
            (table, priced[table.table_id]) for table in tables.values() if table.table_id in priced
        ]

    def _in_price_state(
        self,
        context: ValidationContext,
        config: BoqBidPricesConfig,
        table: Table,
        record: ItemRecord,
    ) -> bool:
        if record.unit_price is not None or self._by_type(config, record):
            return True
        marker = context.marker(table, table.row(record.row_id), config.unit_price_field)
        return marker is ValueMarker.NOT_OFFERED

    def _by_type(self, config: BoqBidPricesConfig, record: ItemRecord) -> bool:
        return bool(record.item_type and search_text(config.not_offered_pattern, record.item_type))

    def _is_zero(self, config: BoqBidPricesConfig, record: ItemRecord) -> bool:
        if record.unit_price is None or record.unit_price != 0 or record.quantity == 0:
            return False
        return not self._excluded(config, record)

    def _is_token(self, config: BoqBidPricesConfig, record: ItemRecord) -> bool:
        if record.unit_price is None or record.unit_price not in config.token_prices:
            return False
        return not self._excluded(config, record)

    def _is_negative(self, config: BoqBidPricesConfig, record: ItemRecord) -> bool:
        """A unit price below zero on a position that is offered and whose texts do not call
        it a credit or deduction."""
        if record.unit_price is None or record.unit_price >= 0 or self._excluded(config, record):
            return False
        texts = [t for t in (record.description, record.long_description, record.item_type) if t]
        return not any(search_text(config.credit_pattern, text) for text in texts)

    def _with_tax(
        self, config: BoqBidPricesConfig, record: ItemRecord
    ) -> tuple[Decimal, Decimal] | None:
        """The net price and the rate when the unit price is no whole cent amount but exactly
        a whole cent amount plus one of the value added tax rates."""
        price = record.unit_price
        if price is None or price <= 0 or self._excluded(config, record):
            return None
        if price == price.quantize(_CENT):
            return None
        for rate in config.vat_rates:
            net = (price * 100 / (100 + rate)).quantize(_CENT)
            if net > 0 and net * (100 + rate) / 100 == price:
                return net, rate
        return None

    def _excluded(self, config: BoqBidPricesConfig, record: ItemRecord) -> bool:
        """An item type that says the position is omitted or not offered (not a position
        outside the sum: an alternative must be priced too)."""
        return bool(
            record.item_type and search_text(config.excluded_item_type_pattern, record.item_type)
        )

    def _below_floor(
        self,
        context: ValidationContext,
        config: BoqBidPricesConfig,
        table: Table,
        record: ItemRecord,
        result: DetectorResult,
    ) -> bool:
        if record.unit_price is None or record.unit_price >= config.hourly_wage_floor:
            return False
        texts = [t for t in (record.description, record.long_description) if t]
        if not is_hourly_labour(
            record.item_type,
            record.unit_id,
            texts,
            hour_unit_ids=config.hour_unit_ids,
            item_type_pattern=config.hourly_item_type_pattern,
            labour_pattern=config.labour_pattern,
        ):
            return False
        row = table.row(record.row_id)
        currency = context.currency_evidence(table, row, [config.unit_price_field])
        if currency is not None and currency != config.floor_currency:
            result.count(OTHER_CURRENCY)
            return False
        return True

    # ------------------------------------------------------------------ findings
    def _token(
        self,
        context: ValidationContext,
        config: BoqBidPricesConfig,
        table: Table,
        record: ItemRecord,
        *,
        rule_id: str,
    ) -> ValidationIssue:
        label = _label(table, record)
        price = fmt(record.unit_price) or ""
        if rule_id == RULE_ZERO:
            quantity = fmt(record.quantity)
            title = f"Unit price {price} in {label}"
            explanation = (
                f"{label} has a unit price of {price}"
                + (f" for a quantity of {quantity}" if quantity else "")
                + ": the work is offered free of charge, or its price was left out."
            )
            rule_detail = (
                "A unit price of 0,00 on a position whose quantity is not 0 and that is neither "
                "'entfällt' nor 'nicht angeboten' (GAEB 3.3 §4.6.4 keeps 0,00 apart from a "
                "missing price)."
            )
            action = ZERO_RECOMMENDATION
        else:
            title = f"Token unit price {price} in {label}"
            explanation = (
                f"{label} has a unit price of {price}. A token price usually means its cost was "
                "priced into other positions."
            )
            rule_detail = (
                "A unit price of "
                + " or ".join(fmt(p) or "" for p in config.token_prices)
                + " on a position that is neither 'entfällt' nor 'nicht angeboten'."
            )
            action = NOMINAL_RECOMMENDATION
        if record.counts_toward_totals is False:
            explanation += (
                " The position does not count toward the total, but an alternative or "
                "contingency position must be priced too (GAEB 3.3 §4.5.2)."
            )
        return context.issues.create(
            self.spec,
            rule_id=rule_id,
            category=CATEGORY_PRICE,
            severity=Severity.MEDIUM,
            evidence_class=EvidenceClass.SUSPECTED_ANOMALY,
            title=clip(title, 200),
            explanation=explanation,
            table=table,
            row=table.row(record.row_id),
            cells=_cells(record, config.unit_price_field),
            observed_value=price,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.VALUE,
                    label="Unit price",
                    detail=price,
                    cells=_cells(record, config.unit_price_field),
                    data={"unit_price": price},
                ),
                EvidenceItem(
                    kind=EvidenceKind.RULE,
                    label="Zero price rule" if rule_id == RULE_ZERO else "Token price rule",
                    detail=rule_detail,
                    data={"rule_id": rule_id},
                ),
            ],
            suggested_action=action,
        )

    def _not_offered(
        self,
        context: ValidationContext,
        config: BoqBidPricesConfig,
        table: Table,
        record: ItemRecord,
        *,
        by_type: bool,
    ) -> ValidationIssue:
        label = _label(table, record)
        row = table.row(record.row_id)
        if by_type:
            source_field, source_label = config.item_type_field, "Item type"
            written = record.item_type or ""
            explanation = f"{label} is marked 'nicht angeboten' (item type '{written}')"
        else:
            source_field, source_label = config.unit_price_field, "Unit price"
            written = context.text(table, row, config.unit_price_field) or ""
            explanation = f"{label} has '{written}' as its unit price"
        explanation += ", so the bid has no price for it."
        outside = record.counts_toward_totals is False
        if outside:
            explanation += (
                " The position is declared outside the sum, so it adds nothing to the total, "
                "but the base and every alternative execution are to be offered (GAEB 3.3 "
                "§4.5.2)."
            )
        if _count_undetermined(context, table, config):
            explanation += " " + config.undetermined_count_note.strip()
        cells = _cells(record, *dict.fromkeys((source_field, config.unit_price_field)))
        return context.issues.create(
            self.spec,
            rule_id=RULE_NOT_OFFERED,
            category=CATEGORY_COMPLETENESS,
            severity=Severity.MEDIUM if outside else Severity.HIGH,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"{label} is not offered", 200),
            explanation=explanation,
            table=table,
            row=row,
            cells=cells,
            observed_value=written,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.VALUE,
                    label=source_label,
                    detail=written,
                    cells=_cells(record, source_field),
                ),
                EvidenceItem(
                    kind=EvidenceKind.RULE,
                    label="Not offered",
                    detail=(
                        "A position whose GAEB item type says 'nicht angeboten', or whose unit "
                        "price is a 'not offered' marker."
                    ),
                    data={"rule_id": RULE_NOT_OFFERED, "outside_the_sum": outside},
                ),
            ],
            suggested_action=NOT_OFFERED_RECOMMENDATION,
        )

    def _negative(
        self,
        context: ValidationContext,
        config: BoqBidPricesConfig,
        table: Table,
        record: ItemRecord,
    ) -> ValidationIssue:
        label = _label(table, record)
        price = fmt(record.unit_price) or ""
        cells = _cells(record, config.unit_price_field)
        return context.issues.create(
            self.spec,
            rule_id=RULE_NEGATIVE,
            category=CATEGORY_PRICE,
            severity=Severity.HIGH,
            evidence_class=EvidenceClass.SUSPECTED_ANOMALY,
            title=clip(f"Negative unit price {price} in {label}", 200),
            explanation=(
                f"{label} has a unit price of {price}, below zero, and its text does not call "
                "it a credit or deduction. The bidder would pay the client for this work, so "
                "the sign is wrong or a credit is not declared. The line total can still "
                "multiply correctly."
            ),
            table=table,
            row=table.row(record.row_id),
            cells=cells,
            observed_value=price,
            expected_value=">= 0",
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.VALUE,
                    label="Unit price",
                    detail=price,
                    cells=cells,
                    data={"unit_price": price},
                ),
                EvidenceItem(
                    kind=EvidenceKind.RULE,
                    label="Negative price rule",
                    detail=(
                        "A unit price below zero on a position that is offered and whose "
                        "texts name no credit or deduction (Gutschrift, Abzug, Nachlass, ...)."
                    ),
                    data={"rule_id": RULE_NEGATIVE},
                ),
            ],
            suggested_action=NEGATIVE_RECOMMENDATION,
        )

    def _tax(
        self,
        context: ValidationContext,
        config: BoqBidPricesConfig,
        table: Table,
        record: ItemRecord,
        net: Decimal,
        rate: Decimal,
    ) -> ValidationIssue:
        label = _label(table, record)
        price = fmt(record.unit_price) or ""
        net_text, rate_text = fmt(net) or "", fmt(rate) or ""
        cells = _cells(record, config.unit_price_field)
        return context.issues.create(
            self.spec,
            rule_id=RULE_TAX,
            category=CATEGORY_PRICE,
            severity=Severity.MEDIUM,
            evidence_class=EvidenceClass.SUSPECTED_ANOMALY,
            title=clip(f"Unit price {price} in {label} is {net_text} plus {rate_text}% VAT", 200),
            explanation=(
                f"{label} has a unit price of {price}, which is not a whole cent amount but is "
                f"exactly {net_text} plus {rate_text}% value added tax. The unit prices of a "
                "bill are net, so this price is likely gross and the tax would be charged twice."
            ),
            table=table,
            row=table.row(record.row_id),
            cells=cells,
            observed_value=price,
            expected_value=net_text,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label="Unit price and net price",
                    detail=f"{price} = {net_text} x {fmt((100 + rate) / 100)}",
                    cells=cells,
                    data={"unit_price": price, "net_price": net_text, "vat_rate": rate_text},
                ),
                EvidenceItem(
                    kind=EvidenceKind.RULE,
                    label="Tax in unit price rule",
                    detail=(
                        "A unit price that is not a whole cent amount and equals a whole cent "
                        "amount plus a value added tax rate."
                    ),
                    data={"rule_id": RULE_TAX},
                ),
            ],
            suggested_action=TAX_RECOMMENDATION,
        )

    def _discount(
        self, context: ValidationContext, table: Table, record: ItemRecord
    ) -> ValidationIssue:
        label = _label(table, record)
        discount = fmt(record.discount_percent) or ""
        cells = _cells(record, "discount_percent")
        return context.issues.create(
            self.spec,
            rule_id=RULE_DISCOUNT,
            category=CATEGORY_PRICE,
            severity=Severity.MEDIUM,
            evidence_class=EvidenceClass.SUSPECTED_ANOMALY,
            title=clip(f"Item discount {discount}% in {label} exceeds the whole price", 200),
            explanation=(
                f"{label} has an item discount of {discount}%, above 100%. This changes the "
                "sign of the extended price rather than just reducing it, even when the "
                "line total has been recomputed consistently."
            ),
            table=table,
            row=table.row(record.row_id),
            cells=cells,
            observed_value=discount,
            expected_value="<= 100%",
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label="Item discount and full price",
                    detail=f"{discount}% > 100%",
                    cells=cells,
                )
            ],
            suggested_action="Check the item discount and its percentage basis before submission.",
        )

    def _floor(
        self,
        context: ValidationContext,
        config: BoqBidPricesConfig,
        table: Table,
        record: ItemRecord,
    ) -> ValidationIssue:
        label = _label(table, record)
        price = fmt(record.unit_price) or ""
        floor = fmt(config.hourly_wage_floor) or ""
        return context.issues.create(
            self.spec,
            rule_id=RULE_FLOOR,
            category=CATEGORY_PRICE,
            severity=Severity.HIGH,
            evidence_class=EvidenceClass.SUSPECTED_ANOMALY,
            title=clip(f"Hourly rate {price} in {label} is below the minimum wage", 200),
            explanation=(
                f"{label} prices an hour of labour at {price}, below the {config.floor_source} "
                f"({floor} {config.floor_currency})."
            ),
            table=table,
            row=table.row(record.row_id),
            cells=_cells(record, config.unit_price_field),
            observed_value=price,
            expected_value=f">= {floor}",
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label="Hourly rate and floor",
                    detail=f"{price} < {floor} {config.floor_currency}",
                    cells=_cells(record, config.unit_price_field),
                    data={
                        "unit_price": price,
                        "floor": floor,
                        "currency": config.floor_currency,
                    },
                ),
                EvidenceItem(
                    kind=EvidenceKind.RULE,
                    label="Hourly labour",
                    detail=(
                        "A position in hours whose item type is Stundenlohnarbeiten or whose "
                        "text names labour (Facharbeiter, Bauwerker, Helfer, Lohn, ...)."
                    ),
                    data={"rule_id": RULE_FLOOR, "source": config.floor_source},
                ),
            ],
            suggested_action=FLOOR_RECOMMENDATION.format(
                floor=floor, currency=config.floor_currency
            ),
        )


def _count_undetermined(
    context: ValidationContext, table: Table, config: BoqBidPricesConfig
) -> bool:
    """True when the file does not say which positions count (an extraction warning in
    ``undetermined_count_warnings``, for the whole file or for this table)."""
    codes = set(config.undetermined_count_warnings)
    return bool(codes) and any(
        warning.code in codes and warning.table_id in (None, table.table_id)
        for warning in context.dataset.extraction.warnings
    )


def _label(table: Table, record: ItemRecord) -> str:
    if record.item_code:
        return record.item_code
    return f"'{table.name}' row {table.row(record.row_id).source_row_number}"


def _cells(record: ItemRecord, *field_ids: str) -> list[CellRef]:
    return [cell for f in field_ids if (cell := record.cell(f)) is not None]
