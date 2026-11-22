"""Domain profiles: the replaceable, domain-specific configuration layer.

The validation core is generic. Everything construction-specific (header synonyms such as
"Einheitspreis", subtotal wording such as "Summe Titel", unit vocabularies, value markers such
as "entfällt", advisory unit rules, detector parameter defaults) lives in a profile file such as
``app/profiles/boq.yaml``. A new challenge gets a new profile, not a rewrite.

Patterns in profiles are case-insensitive regular expressions, compiled and applied only
through :mod:`app.core.patterns` (bounded text length, memoized), never with ``re`` directly.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.core import patterns
from app.models.base import FrozenModel
from app.models.dataset import RowKind
from app.models.plan import DETECTOR_ID_PATTERN
from app.models.values import ZERO_CONTRIBUTION_MARKERS, DataType, ExactDecimal, ValueMarker

FIELD_ID_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
RULE_ID_PATTERN = r"^[a-z][a-z0-9_.]{0,63}$"
PROFILE_FIELD_TYPES = frozenset(
    {DataType.TEXT, DataType.NUMBER, DataType.DATE, DataType.DATETIME, DataType.BOOLEAN}
)


def _compile(pattern: str) -> re.Pattern[str]:
    return patterns.compile_pattern(pattern)


_TOKEN_SPACE = re.compile(r"\s+")


def normalize_token(text: str) -> str:
    """Comparison key for short conventional tokens (value markers): NFKC, case folded,
    inner whitespace collapsed, outer whitespace removed. ``' Incl. '`` -> ``'incl.'``."""
    return _TOKEN_SPACE.sub(" ", unicodedata.normalize("NFKC", text)).strip().casefold()


class FieldRole(StrEnum):
    IDENTIFIER = "identifier"  # item code / position number
    LABEL = "label"  # description text
    QUANTITY = "quantity"
    UNIT = "unit"
    MONETARY = "monetary"  # prices and totals; subject to currency checks
    CURRENCY = "currency"  # a column holding currency codes
    REFERENCE = "reference"  # points at another row's identifier
    CATEGORY = "category"
    OTHER = "other"


class FieldConstraints(FrozenModel):
    """Declarative constraints evaluated by the deterministic detectors.

    ``unique_scope``: ``table`` = unique among the item rows of a table; ``section`` = unique
    within the innermost section, where a carry-forward row (page break) also starts a new
    scope, because some layouts restart item letters on every page.
    """

    minimum: ExactDecimal | None = None
    maximum: ExactDecimal | None = None
    exclusive_minimum: bool = False
    exclusive_maximum: bool = False
    integer_only: bool = False
    max_decimal_places: int | None = Field(default=None, ge=0, le=12)
    allow_zero: bool = True
    pattern: str | None = None  # full match, case-insensitive, for text values
    allowed_values: list[str] | None = None  # compared case-insensitively after normalization
    unique: bool = False
    unique_scope: Literal["table", "section"] = "table"

    @field_validator("pattern")
    @classmethod
    def _pattern_compiles(cls, value: str | None) -> str | None:
        if value is not None:
            _compile(value)
        return value


class SemanticField(FrozenModel):
    """A field of the domain vocabulary.

    Header matching (normalization): ``header_synonyms`` may match the whole normalized header
    or a contiguous run of its words; synonyms shorter than the profile's
    ``normalization.min_contains_chars`` (default 4) and all ``exact_header_synonyms`` match
    only the whole normalized header (so "me" never matches "Bemerkung" and "preis" never
    matches "Preis GP"). ``match_headers: false`` keeps a field out of header matching
    altogether: only a file's declared structure (a GAEB bill) or a reviewer maps it, so a
    look-alike spreadsheet header never feeds a rule that needs exactly that meaning.
    ``match_headers: exact`` matches only ``exact_header_synonyms``, with no implicit label,
    field-id, substring or fuzzy aliases.
    """

    field_id: str = Field(pattern=FIELD_ID_PATTERN)
    label: str
    description: str = ""
    data_type: DataType
    role: FieldRole = FieldRole.OTHER
    required: bool = False
    required_row_kinds: list[RowKind] = Field(default_factory=lambda: [RowKind.ITEM])
    header_synonyms: list[str] = Field(default_factory=list)
    exact_header_synonyms: list[str] = Field(default_factory=list)
    match_headers: bool | Literal["exact"] = True
    constraints: FieldConstraints | None = None

    @field_validator("data_type")
    @classmethod
    def _supported_type(cls, value: DataType) -> DataType:
        if value not in PROFILE_FIELD_TYPES:
            raise ValueError(f"Field data_type must be one of {sorted(PROFILE_FIELD_TYPES)}")
        return value


class SectionPattern(FrozenModel):
    """A section heading pattern. ``level`` (1 = outermost) is used when the heading carries
    no hierarchical code. An optional named group ``code`` extracts a code from the label
    ("Titel 01 Erdarbeiten" -> ``01``)."""

    pattern: str
    level: int | None = Field(default=None, ge=1, le=9)

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value: str) -> str:
        _compile(value)
        return value


TotalsTextSource = Literal["label", "category", "amount_text", "continuation_text"]


def _label_only() -> list[TotalsTextSource]:
    return ["label"]


class TotalsRule(FrozenModel):
    """Decides whether an ITEM (or every item of a SECTION) is added into totals.

    Rules are tried in order and the first match wins, so a specific rule ("Bedarfsposition
    mit GB" counts) must come before a general one ("Bedarfsposition": unknown).
    ``applies_to`` names where the pattern is searched: ``label`` (label fields),
    ``category`` (fields with role category, e.g. an item-type column), ``amount_text``
    (non-numeric text in monetary cells, e.g. "nur EP" in the total column) and
    ``continuation_text`` (TEXT rows that continue the item).
    ``counts_toward_totals``: True, False, or None for "cannot tell from the document".
    """

    rule_id: str = Field(pattern=RULE_ID_PATTERN)
    pattern: str
    applies_to: list[TotalsTextSource] = Field(default_factory=_label_only, min_length=1)
    counts_toward_totals: bool | None

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value: str) -> str:
        _compile(value)
        return value


@dataclass(frozen=True, slots=True)
class LabelMatch:
    """Result of :meth:`RowClassificationRules.match_label`."""

    kind: RowKind | None  # None for a summary-block heading (it is not a row kind of its own)
    rule: str  # e.g. "pattern.subtotal", "pattern.summary_block"
    matched_text: str
    code: str | None = None  # value of the pattern's named group "code", if any
    level: int | None = None  # SECTION patterns only

    @property
    def starts_summary_block(self) -> bool:
        return self.rule == SUMMARY_BLOCK_RULE


SUMMARY_BLOCK_RULE = "pattern.summary_block"


class RowClassificationRules(FrozenModel):
    """How normalization classifies rows. The decision table (``build_dataset`` contract):

    1. ``blank``: no non-empty cell.
    2. Label matching (:meth:`match_label`) on the label text (the first non-empty of
       ``label_fields``, else the first text cell when ``fallback_to_first_text_cell``), in
       this precedence: carry-forward, gross total, tax, grand total, adjustment, summary-block
       heading, subtotal, section. A carried running total is never a scope total, and gross
       wording ("inkl. MwSt.") wins over grand-total wording ("Gesamtsumme").
    3. A total-like match (carry-forward, gross, tax, grand, adjustment, subtotal) gives that
       kind only when the quantity is empty and not both unit price and line total are filled
       (a row with a quantity or with a rate and an amount is an item, whatever its text), and
       only when some amount cell is non-empty; without an amount the row is ``text``.
    4. Inside a summary block (after a summary-block heading, up to and including the next
       subtotal, grand or gross total), a row with an amount and neither quantity nor unit
       price is a ``summary_line``.
    5. ``item``: quantity or unit price filled, or line total and unit filled (lump sums).
    6. ``section``: a section pattern matched, or the row's code (``section_code_field``, or
       the pattern's ``code`` group) is a strict prefix of the next item's code; and neither
       quantity nor unit price is filled.
    7. Anything else with a numeric cell is ``text`` with a needs-review warning
       ``unclassified_amount_row``; everything else is ``text``.

    ``totals_rules`` (:meth:`match_totals`) then decide ``counts_toward_totals`` for items;
    a SECTION row's match is inherited by the items of that section.
    """

    label_fields: list[str] = Field(default_factory=list)
    fallback_to_first_text_cell: bool = True
    carry_forward_patterns: list[str] = Field(default_factory=list)
    gross_total_patterns: list[str] = Field(default_factory=list)
    tax_patterns: list[str] = Field(default_factory=list)
    grand_total_patterns: list[str] = Field(default_factory=list)
    adjustment_patterns: list[str] = Field(default_factory=list)
    summary_block_patterns: list[str] = Field(default_factory=list)
    subtotal_patterns: list[str] = Field(default_factory=list)
    section_patterns: list[SectionPattern] = Field(default_factory=list)
    totals_rules: list[TotalsRule] = Field(default_factory=list)
    item_value_fields: list[str] = Field(default_factory=list)
    section_code_field: str | None = None
    section_code_pattern: str | None = None  # optional extra constraint on section codes

    @field_validator("section_patterns", mode="before")
    @classmethod
    def _plain_strings(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [{"pattern": v} if isinstance(v, str) else v for v in value]
        return value

    @model_validator(mode="after")
    def _patterns_compile(self) -> RowClassificationRules:
        for name, _, _ in _LABEL_PRECEDENCE:
            for pattern in getattr(self, name):
                _compile(pattern)
        if self.section_code_pattern:
            _compile(self.section_code_pattern)
        rule_ids = [r.rule_id for r in self.totals_rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("Duplicate totals rule ids")
        return self

    def match_label(self, text: str | None) -> LabelMatch | None:
        """First matching pattern in precedence order (see the class docstring), or ``None``.
        Only the first :data:`app.core.patterns.MAX_MATCH_CHARS` characters are examined."""
        if not text or not text.strip():
            return None
        for list_name, kind, rule in _LABEL_PRECEDENCE:
            for pattern in getattr(self, list_name):
                found = patterns.search(pattern, text)
                if found:
                    return LabelMatch(kind, rule, found.group(0), _code_group(found))
        for section in self.section_patterns:
            found = patterns.search(section.pattern, text)
            if found:
                return LabelMatch(
                    RowKind.SECTION,
                    "pattern.section",
                    found.group(0),
                    _code_group(found),
                    section.level,
                )
        return None

    def match_totals(self, texts: Mapping[TotalsTextSource, Sequence[str]]) -> TotalsRule | None:
        """First totals rule (in order) whose pattern is found in any of the texts it
        applies to, or ``None`` when no rule matches (the item counts by default)."""
        for rule in self.totals_rules:
            for source in rule.applies_to:
                for text in texts.get(source, ()):
                    if text and patterns.search(rule.pattern, text):
                        return rule
        return None


# (pattern list, kind, rule) in label-matching precedence; section patterns come last.
_LABEL_PRECEDENCE: tuple[tuple[str, RowKind | None, str], ...] = (
    ("carry_forward_patterns", RowKind.CARRY_FORWARD, "pattern.carry_forward"),
    ("gross_total_patterns", RowKind.GROSS_TOTAL, "pattern.gross_total"),
    ("tax_patterns", RowKind.TAX, "pattern.tax"),
    ("grand_total_patterns", RowKind.GRAND_TOTAL, "pattern.grand_total"),
    ("adjustment_patterns", RowKind.ADJUSTMENT, "pattern.adjustment"),
    ("summary_block_patterns", None, SUMMARY_BLOCK_RULE),
    ("subtotal_patterns", RowKind.SUBTOTAL, "pattern.subtotal"),
)


def _code_group(found: re.Match[str]) -> str | None:
    if "code" not in found.re.groupindex:
        return None
    code = found.group("code")
    return code.strip() if code and code.strip() else None


class UnitDefinition(FrozenModel):
    """A unit of the profile's vocabulary.

    ``quantity_factor`` converts a quantity in this unit into the multiplier used for
    line totals: 1 for ordinary units, 0.01 for percent items (qty 5 % of a base amount
    priced as the rate gives total = 5 × 0.01 × rate). It applies only when neither the
    quantity nor the unit price is itself a percentage value (already divided by 100).
    """

    unit_id: str = Field(min_length=1, max_length=32)
    label: str
    dimension: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    aliases: list[str] = Field(default_factory=list)
    integer_quantities: bool = False  # advisory: count units usually take whole numbers
    quantity_factor: ExactDecimal = Field(default=Decimal(1), gt=0)


class ValueMarkerRule(FrozenModel):
    """Conventional tokens that may stand in a numeric cell instead of a number, and what
    they mean. Tokens are compared whole, after :func:`normalize_token`. ``roles`` limits the
    rule to fields with these roles (default: quantities and monetary fields)."""

    marker: ValueMarker
    tokens: list[str] = Field(min_length=1)
    roles: list[FieldRole] = Field(
        default_factory=lambda: [FieldRole.QUANTITY, FieldRole.MONETARY], min_length=1
    )


class BooleanWords(FrozenModel):
    """Words that mean yes or no in a yes/no field, compared after removing outer whitespace
    and case folding. Spreadsheet booleans need no words. A profile without words reads no
    yes/no text (such cells are reported as unreadable, never guessed)."""

    true_words: list[str] = Field(default_factory=list)
    false_words: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _distinct(self) -> BooleanWords:
        true = [word.strip().casefold() for word in self.true_words]
        false = [word.strip().casefold() for word in self.false_words]
        if not all([*true, *false]):
            raise ValueError("Empty yes/no word")
        both = sorted(set(true) & set(false))
        if both:
            raise ValueError(f"Words mean both yes and no: {both}")
        return self


class NormalizationThresholds(FrozenModel):
    """Normalization thresholds a domain may tune. Deployment-wide tunables (header scan
    rows, type dominance, the fuzzy header ratio) are ``Settings.normalization``.

    * ``type_mismatch_share``, ``type_mismatch_min_values``: a column mapped to a number field
      by its header loses that mapping when it holds at least ``type_mismatch_min_values``
      values and fewer than ``type_mismatch_share`` of them are numbers.
    * ``min_contains_chars``: header synonyms at least this long may match a contiguous run of
      a longer header's words; shorter ones match only the whole header.
    * ``min_fuzzy_chars``: headers at least this long may match a synonym by approximate
      spelling.
    * ``structural_lookahead_rows``, ``data_lookahead_rows``: structural header detection
      needs a number within this many rows after the candidate row, and data below the
      candidate's text cells within this many rows.
    """

    type_mismatch_share: float = Field(default=0.5, gt=0, le=1)
    type_mismatch_min_values: int = Field(default=3, ge=1)
    min_contains_chars: int = Field(default=4, ge=1, le=64)
    min_fuzzy_chars: int = Field(default=4, ge=1, le=64)
    structural_lookahead_rows: int = Field(default=3, ge=1, le=50)
    data_lookahead_rows: int = Field(default=20, ge=1, le=500)


class LocaleSettings(FrozenModel):
    """``parenthesized_numbers``: what "(1.234,00)" means. ``negative`` (accounting) parses it
    as a negative number; ``ambiguous`` leaves it unparsed (in German LV printouts
    parentheses can mean "not included in the total")."""

    decimal_separator: Literal["auto", ".", ","] = "auto"
    date_order: Literal["auto", "DMY", "MDY", "YMD"] = "auto"
    default_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    parenthesized_numbers: Literal["negative", "ambiguous"] = "negative"


class DomainProfile(FrozenModel):
    profile_id: str = Field(pattern=FIELD_ID_PATTERN)
    name: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str = ""
    locale: LocaleSettings = Field(default_factory=LocaleSettings)
    fields: list[SemanticField] = Field(default_factory=list)
    row_classification: RowClassificationRules = Field(default_factory=RowClassificationRules)
    units: list[UnitDefinition] = Field(default_factory=list)
    value_markers: list[ValueMarkerRule] = Field(default_factory=list)
    currency_aliases: dict[str, str] = Field(default_factory=dict)
    detector_defaults: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Value markers whose amount contributes zero to a total (the total is complete without a
    # number); any other marker in an amount makes the scope incomplete.
    zero_contribution_markers: list[ValueMarker] = Field(
        default_factory=lambda: [m for m in ValueMarker if m in ZERO_CONTRIBUTION_MARKERS]
    )
    boolean_words: BooleanWords = Field(default_factory=BooleanWords)
    normalization: NormalizationThresholds = Field(default_factory=NormalizationThresholds)

    @model_validator(mode="after")
    def _consistent(self) -> DomainProfile:
        field_ids = [f.field_id for f in self.fields]
        duplicates = {f for f in field_ids if field_ids.count(f) > 1}
        if duplicates:
            raise ValueError(f"Duplicate field ids: {sorted(duplicates)}")
        known = set(field_ids)
        rules = self.row_classification
        referenced = set(rules.label_fields) | set(rules.item_value_fields)
        if rules.section_code_field:
            referenced.add(rules.section_code_field)
        unknown = referenced - known
        if unknown:
            raise ValueError(f"Row classification references unknown fields: {sorted(unknown)}")
        unit_ids = [u.unit_id for u in self.units]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("Duplicate unit ids")
        seen_tokens: dict[str, ValueMarker] = {}
        for rule in self.value_markers:
            for token in rule.tokens:
                key = normalize_token(token)
                if not key:
                    raise ValueError("Empty value marker token")
                for role in rule.roles:
                    previous = seen_tokens.get(f"{role}:{key}")
                    if previous is not None and previous is not rule.marker:
                        raise ValueError(
                            f"Value marker token {token!r} means both {previous} and {rule.marker}"
                        )
                    seen_tokens[f"{role}:{key}"] = rule.marker
        if len(set(self.zero_contribution_markers)) != len(self.zero_contribution_markers):
            raise ValueError("zero_contribution_markers lists a marker twice")
        for code in self.currency_aliases.values():
            if not re.fullmatch(r"[A-Z]{3}", code):
                raise ValueError(f"Currency alias target {code!r} is not an ISO 4217 code")
        for detector_id in self.detector_defaults:
            if not re.fullmatch(DETECTOR_ID_PATTERN, detector_id):
                raise ValueError(f"Invalid detector id {detector_id!r}")
        return self

    def field(self, field_id: str) -> SemanticField | None:
        return next((f for f in self.fields if f.field_id == field_id), None)

    def fields_with_role(self, role: FieldRole) -> list[SemanticField]:
        return [f for f in self.fields if f.role is role]

    def required_fields(self, row_kind: RowKind = RowKind.ITEM) -> list[SemanticField]:
        return [f for f in self.fields if f.required and row_kind in f.required_row_kinds]

    def match_marker(self, text: str | None, role: FieldRole) -> ValueMarker | None:
        """Meaning of ``text`` as a value marker for a field with ``role``, or ``None``."""
        if not text or len(text) > 40:
            return None
        key = normalize_token(text)
        for rule in self.value_markers:
            if role in rule.roles and any(normalize_token(t) == key for t in rule.tokens):
                return rule.marker
        return None
