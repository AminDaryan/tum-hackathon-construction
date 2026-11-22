"""Required attributes: positions whose price depends on a property the text does not state.

Read as the bidder pricing a client's tender. One finding per table and rule, listing the
positions:

* ``disposal_waste_class``: disposal (entsorgen, deponieren, verwerten) of a mineral or filter
  material (Boden, Bauschutt, Beton, Asphalt, Filterkies, ...) without a waste class: no AVV
  code, no class under the Ersatzbaustoffverordnung, the DepV or LAGA (Z 0 ... Z 2, DK 0 ...
  III, BM-0 ... BM-F3, RC-1 ... RC-3), no "unbelastet" or "gefährlich", no analysis. A class
  the text says is still open ("AVV und LAGA-Klasse noch festzulegen") is no class.
* ``concrete_strength_class``: concrete made or placed on site (Ortbeton, Normalbeton,
  Magerbeton, Beton einbauen, Stahlbeton or Transportbeton with a verb of placing, ...)
  without a strength class (C 8/10 ... C 100/115, LC ...); precast parts, demolition and
  removal are not concrete work here, nor is a Kurztext that opens with formwork,
  reinforcement, a coating, cutting or an opening.
* ``pipe_dimension``: a pipe or fitting supplied or laid (Rohr, Rohrleitung, Bogen, Winkel,
  T-Stück, Muffe, Flansch, Kappe, Schieber, ...) without a dimension (DN, OD, da, d =, Ø,
  "63 x 5,8", "110 mm", ...); marking tape, bedding, protection pipes and removal are not.

Severity medium, evidence ``semantic_warning``: the check reads wording, and the attribute
can be stated somewhere the check does not read (a drawing, the preamble). For the strength
class and the pipe dimension, the recommendation quotes a position of the same section that
states one, when there is one. Finding category (for the category table):
``domain.boq_required_attributes -> ambiguity`` for every rule.

A position's text is its Kurztext and Langtext with continuation lines; rows are read
directly, not through the item frame, see :mod:`._bill_text`. The rules are detector
configuration with the defaults below, measured on five sample bills before the GAEB import
read them; a profile can replace them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import Field, field_validator, model_validator

from app.models.base import FrozenModel
from app.models.issue import (
    RULE_ID_PATTERN,
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    Severity,
    ValidationIssue,
)
from app.models.values import DataType
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
from app.validation.deterministic._support import FieldId
from app.validation.domain.boq._bill_text import (
    Bill,
    BillFields,
    Entry,
    Found,
    description_applicability,
    entry_cells,
    list_codes,
    read_bill,
    search,
    search_all,
    search_start,
)

RULE_WASTE_CLASS = "disposal_waste_class"
RULE_STRENGTH_CLASS = "concrete_strength_class"
RULE_PIPE_DIMENSION = "pipe_dimension"
CATEGORY = "missing_attribute"
MAX_QUOTES = 3

ITEMS_READ = "items_read"
TRIGGER_ITEMS = "trigger_items"
TRIGGERS_EXCLUDED = "trigger_items_excluded"
TRIGGERS_WITH_ATTRIBUTE = "trigger_items_with_attribute"

_UE, _AE, _OE, _SS = "(?:ü|ue)", "(?:ä|ae)", "(?:ö|oe)", "(?:ß|ss)"


class TextPart(StrEnum):
    """Which text of a position a condition reads."""

    DESCRIPTION = "description"  # the Kurztext
    LONG_DESCRIPTION = "long_description"  # the Langtext with continuation lines
    BOTH = "both"


class TextCondition(FrozenModel):
    """``pattern`` (case-insensitive) is found in ``part``; with ``at_start`` only in the
    text's first window, for patterns anchored with ``^``."""

    pattern: str
    part: TextPart = TextPart.DESCRIPTION
    at_start: bool = False

    @field_validator("pattern")
    @classmethod
    def _valid_pattern(cls, value: str) -> str:
        return checked_pattern(value, groups=None)


class AttributeRule(FrozenModel):
    """Positions that match all conditions of one of ``triggers`` and none of ``excludes``,
    and whose Kurz- and Langtext do not match ``attribute_pattern`` (or match
    ``open_pattern``: the text says the attribute is not decided yet), are listed.
    ``ignore_in_description`` is wording blanked out of the Kurztext before trigger
    conditions read it (a "Straßenkappe" is not a pipe cap)."""

    rule_id: str = Field(pattern=RULE_ID_PATTERN)
    title: str = Field(min_length=1, max_length=120)
    described: str = Field(min_length=1, max_length=200)
    attribute: str = Field(min_length=1, max_length=120)
    triggers: tuple[tuple[TextCondition, ...], ...] = Field(min_length=1)
    excludes: tuple[TextCondition, ...] = ()
    ignore_in_description: str | None = None
    attribute_pattern: str
    open_pattern: str | None = None
    neighbour_example: bool = False
    severity: Severity = Severity.MEDIUM
    recommendation: str = Field(min_length=1, max_length=600)

    @field_validator("attribute_pattern", "open_pattern", "ignore_in_description")
    @classmethod
    def _valid_pattern(cls, value: str | None) -> str | None:
        return None if value is None else checked_pattern(value, groups=None)

    @field_validator("triggers")
    @classmethod
    def _non_empty(
        cls, value: tuple[tuple[TextCondition, ...], ...]
    ) -> tuple[tuple[TextCondition, ...], ...]:
        if any(not conditions for conditions in value):
            raise ValueError("every trigger needs at least one condition")
        return value


_CLASS_QUESTION = (
    "Ask a bidder question for the missing {attribute}: without it the price cannot be calculated."
)

WASTE_CLASS_RULE = AttributeRule(
    rule_id=RULE_WASTE_CLASS,
    title="Disposal without a waste class",
    described="the disposal of soil, rubble or filter material",
    attribute="waste class",
    triggers=(
        (
            TextCondition(pattern=r"entsorg|deponie|deponier|verwert"),
            TextCondition(
                part=TextPart.BOTH,
                pattern=(
                    rf"boden|aushub|bodendecke|oberboden|mutterboden|bauschutt|beton|asphalt"
                    rf"|fr{_AE}sgut|filter|st{_UE}tzschicht|\bkies|schotter|schlamm|bankett"
                    rf"|tragschicht|pflaster|mauerwerk"
                ),
            ),
        ),
    ),
    excludes=(
        # Sewers and utility owners, metal parts and cleaning are not mineral waste.
        TextCondition(
            pattern=(
                rf"entsorgungsleitung|ver-\s*/?\s*(?:und\s+)?entsorgungs(?:ltg|leitung)"
                rf"|entsorgungsltg|entsorgungseinr|entsorgungstr{_AE}ger"
                rf"|ver-\s*und\s+entsorgung"
                rf"|rohrleitung|armatur|formst{_UE}ck|stahl|metall|schrott|kabel"
                rf"|\breinig(?:en|ung)\b|\bs{_AE}ubern\b|\bkehren\b"
            ),
        ),
    ),
    attribute_pattern=(
        rf"\bZ\s?0\b|\bZ\s?0\*|\bZ\s?1[.,][12]\b|\bZ\s?2\b|>\s*Z\s?2|\bDK\s?(?:0|I{{1,3}}|[0-3])\b"
        rf"|deponieklasse|\bLAGA\b|\bDepV\b|deponieverordnung|\bAVV|abfallschl{_UE}ssel"
        rf"|(?<!\d)(?:0[1-9]|1\d|20)(?: \d{{2}} \d{{2}}|\d{{4}})\*?(?![\d.,])"
        rf"|\bBM-?F?[0-3]\*?|\bRC-?[1-3]\b|ersatzbaustoffverordnung|\bEBV\b|unbelastet"
        rf"|schadstoffbelastet|\bgef{_AE}hrlich|deklarationsanalyse|einbauklasse"
        rf"|verwertungsklasse|teerhaltig|pechhaltig|\bPAK\b"
    ),
    # Moved from the risk table's D30 (2026-11-21): a class system named with the class left open.
    open_pattern=(
        r"noch\s+(?:festzulegen|zu\s+bestimmen|offen)|wird\s+(?:noch\s+)?festgelegt"
        r"|nach\s+(?:analyse|beprobung)\s+festzulegen"
    ),
    recommendation=(
        "Ask a bidder question: which waste class (an AVV code, a class under the "
        "Ersatzbaustoffverordnung or the DepV) should the disposal price assume, or is there "
        "an analysis? Disposal prices depend on the class. If another class is found after "
        "award, that may become a change order, subject to the contract."
    ),
)

STRENGTH_CLASS_RULE = AttributeRule(
    rule_id=RULE_STRENGTH_CLASS,
    title="Concrete without a strength class",
    described="concrete made or placed on site",
    attribute="strength class",
    triggers=(
        (
            TextCondition(
                pattern=(
                    r"\b(?:ortbeton|normalbeton|unterbeton|magerbeton)"
                    r"|sauberkeitsschicht\s+aus\s+beton|betonfundament"
                    r"|fundament\w*\s+aus\s+beton"
                    r"|\bbeton\b(?:\W+\w+){0,3}?\W+(?:herstellen|liefern|einbauen|einbringen)\b"
                    # Stahlbeton and Transportbeton only with a verb of placing: a Kurztext
                    # such as "Oberfläche Stahlbetondecke glätten" is work on concrete.
                    r"|\b(?:stahlbeton\w*|transportbeton(?![\w-]))(?:\W+\w+){0,4}?\W+"
                    r"(?:herstellen|liefern|einbauen|einbringen|betonieren)\b"
                ),
            ),
        ),
        (
            TextCondition(
                part=TextPart.LONG_DESCRIPTION,
                pattern=(
                    r"\b(?:ortbeton|normalbeton|unterbeton|magerbeton)"
                    r"|sauberkeitsschicht\s+aus\s+beton"
                ),
            ),
        ),
    ),
    excludes=(
        # Demolition and removal, precast parts, fillings and core holes.
        TextCondition(
            part=TextPart.BOTH,
            pattern=(
                rf"abbrechen|abbruch|ausbauen|\bausbau\b|aufnehmen|entsorg|fertigteil"
                rf"|vorgefertigt|betonrohr|betonstein|bordstein|pflaster|betonplatte|schacht"
                rf"|rinne|betonring|brunnenring|betonf{_UE}llung|kernbohrung"
            ),
        ),
        # A Kurztext that opens with other work on concrete: formwork, reinforcement, a coating,
        # cutting or an opening ("Schalung für Stahlbetonwand herstellen").
        TextCondition(
            pattern=(
                rf"\A\W*(?:\w+\W+){{0,2}}?(?:schalung|bewehrung|betonstahl|beschicht|anstrich"
                rf"|impr{_AE}gnier|oberfl{_AE}chenschutz|s{_AE}gen|schneiden|durchbruch|bohrung"
                rf"|aussparung|schlitz)"
            ),
        ),
    ),
    attribute_pattern=r"\bL?C\s?\d{1,3}\s?/\s?\d{1,3}\b|festigkeitsklasse",
    neighbour_example=True,
    recommendation=_CLASS_QUESTION.format(attribute="strength class"),
)

_PIPE_HEADS = (
    rf"(?:rohr(?:e|es|en)?|rohrleitung(?:en)?|b{_OE}gen|bogen|winkel|t-st{_UE}ck(?:e)?"
    rf"|reduzierst{_UE}ck(?:e)?|muffe(?:n)?|flansch(?:e|es|en)?|kappe(?:n)?|schieber)"
)

PIPE_DIMENSION_RULE = AttributeRule(
    rule_id=RULE_PIPE_DIMENSION,
    title="Pipes or fittings without a dimension",
    described="the supply or laying of pipes or fittings",
    attribute="dimension (DN, OD or diameter)",
    triggers=(
        # The Kurztext starts with a pipe or fitting word ...
        (
            TextCondition(
                pattern=rf"^(?:[^\w-]|-(?![\w-]))*[\w-]*?{_PIPE_HEADS}(?![\w-])",
                at_start=True,
            ),
        ),
        # ... or names one together with a verb of supply or laying.
        (
            TextCondition(pattern=rf"(?<![\w-])[\w-]*?{_PIPE_HEADS}(?![\w-])"),
            TextCondition(
                pattern=(
                    rf"\b(?:liefern|verlegen|einbauen|montieren|einschwei{_SS}en|setzen"
                    rf"|herstellen|einziehen|anschlie{_SS}en)\b"
                )
            ),
        ),
    ),
    excludes=(
        # Marking tape, bedding, protection, removal, cleaning and inspection.
        TextCondition(
            pattern=(
                rf"trassenband|warnband|markier|einbettung|bettung|\bsand\b|schutzrohr|sichern"
                rf"|ausbau|ausbauen|r{_UE}ckbau|demontage|demontieren|abbrechen|abbruch|entsorg"
                rf"|stilllegen|verd{_AE}mmen|verf{_UE}llen|sp{_UE}len|reinigen|befahren"
                rf"|inspektion|tv-"
            ),
        ),
    ),
    # Words that end in a pipe word but name something else.
    ignore_in_description=(
        rf"stra{_SS}enkappe|schutzkappe|kunststoffkappe|rohrgraben|rohrpfosten|rohrbr{_UE}cke"
        rf"|rohrdurchf{_UE}hrung|rohrabsperrblase|futterrohr|schutzrohr|leerrohr|mantelrohr"
    ),
    attribute_pattern=(
        rf"\bDN\b|\bDN\s?\d|\bOD\b|\bOD\s?\d|\bDA\b|\bDA\s?\d|\bAD\b|\bAD\s?\d|\bd\s?=|\bd\s?\d"
        rf"|\bda\s?\d|[Øø⌀]|au{_SS}endurchmesser|nennweite|innendurchmesser|durchmesser"
        rf"|\bdurchm\.?|\d+(?:[.,]\d+)?\s?x\s?\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s?mm\b"
        rf"|\d+(?:[.,]\d+)?\s?cm\b|\bnw\s?\d|\b\d+\s?zoll\b|\d+\s?\"|\b[1-9]/[248]\s?\""
    ),
    neighbour_example=True,
    recommendation=_CLASS_QUESTION.format(attribute="dimension (DN, OD or diameter)"),
)

DEFAULT_RULES = (WASTE_CLASS_RULE, STRENGTH_CLASS_RULE, PIPE_DIMENSION_RULE)


class RequiredAttributesConfig(DetectorConfig):
    description_field: FieldId = plannable("description", description="Kurztext field.")
    long_description_field: FieldId = plannable("long_description", description="Langtext field.")
    item_code_field: FieldId = plannable("item_code", description="OZ field.")
    rules: tuple[AttributeRule, ...] = Field(
        default=DEFAULT_RULES,
        description="Work and the attribute its price needs (profile-controlled).",
    )
    max_cells_per_issue: int = Field(
        default=20, ge=1, le=200, description="Rows highlighted in one finding."
    )

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> RequiredAttributesConfig:
        ids = [rule.rule_id for rule in self.rules]
        if len(set(ids)) != len(ids):
            raise ValueError("attribute rules must have unique rule ids")
        return self


class RequiredAttributesDetector(Detector[RequiredAttributesConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="domain.boq_required_attributes",
        name="Required attributes (BoQ)",
        version="1.0.0",
        category=DetectorCategory.DOMAIN,
        description=(
            "Lists positions of a bill of quantities whose price depends on a property the "
            "text does not state: disposal without a waste class, concrete without a strength "
            "class, pipes and fittings without a dimension. One finding per bill and rule, "
            "listing the positions."
        ),
        required_fields=("description",),
        optional_fields=("long_description", "item_code"),
        supported_data_types=(DataType.TEXT,),
        applicability="Tables that map the item description (Kurztext).",
        evidence_classes=(EvidenceClass.SEMANTIC_WARNING,),
        issue_categories=(CATEGORY,),
        limitations=(
            "Reads German wording only; the attribute can be stated in a drawing, the "
            "preamble or a note the check does not read, so every finding needs a reviewer.",
            "The default word lists were measured on five sample bills; other bills may "
            "word the same work or attribute differently.",
        ),
        cost="low",
    )
    config_model = RequiredAttributesConfig

    def required_fields(self, config: RequiredAttributesConfig) -> tuple[str, ...]:
        return (config.description_field,)

    def applicability(
        self, context: ValidationContext, config: RequiredAttributesConfig
    ) -> Applicability:
        found = description_applicability(context, config.description_field)
        if found.applicable and not config.rules:
            return Applicability.no("The profile configures no attribute rules.")
        return found

    def validate(
        self, context: ValidationContext, config: RequiredAttributesConfig
    ) -> DetectorResult:
        result = DetectorResult()
        fields = BillFields(
            config.description_field, config.long_description_field, config.item_code_field
        )
        for table in context.tables():
            if not context.has_fields(table, config.description_field):
                continue
            bill = read_bill(context, table, fields)
            result.count(ITEMS_READ, len(bill.items))
            for rule in config.rules:
                context.checkpoint()
                missing, stated = _check(bill, rule, result)
                if missing:
                    result.add(self._issue(context, config, bill, rule, missing, stated))
        return result

    def _issue(
        self,
        context: ValidationContext,
        config: RequiredAttributesConfig,
        bill: Bill,
        rule: AttributeRule,
        missing: list[Entry],
        stated: list[tuple[Entry, Found]],
    ) -> ValidationIssue:
        cells = entry_cells(context, missing, config.description_field, config.max_cells_per_issue)
        quotes = "; ".join(f'{e.label} "{e.quote_short(160)}"' for e in missing[:MAX_QUOTES])
        listed = list_codes(missing)
        noun, verb = ("position", "names") if len(missing) == 1 else ("positions", "name")
        action = rule.recommendation
        example = _neighbour(missing, stated) if rule.neighbour_example else None
        if example is not None:
            entry, found = example
            action += (
                f" Neighbouring positions state it, for example {entry.label} "
                f'"{entry.quote(found, 100)}".'
            )
        return context.issues.create(
            self.spec,
            rule_id=rule.rule_id,
            category=CATEGORY,
            severity=rule.severity,
            evidence_class=EvidenceClass.SEMANTIC_WARNING,
            title=clip(f"{rule.title}: {len(missing)} {noun}", 200),
            explanation=(
                f"{len(missing)} {noun} of this bill {verb} {rule.described} without stating "
                f"a {rule.attribute}: {quotes}"
                + (f" (all {len(missing)}: {listed})" if len(missing) > MAX_QUOTES else "")
                + ". The price depends on it. This is an advisory warning: the "
                f"{rule.attribute} may be stated where the check does not read (a drawing, "
                "the preamble)."
            ),
            table=bill.table,
            cells=cells,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.REFERENCE,
                    label=f"Positions without a {rule.attribute}",
                    detail=clip(listed, 2000),
                    cells=cells,
                    data={"positions": len(missing)},
                ),
            ],
            suggested_action=action,
            subject=rule.rule_id,
        )


def _check(
    bill: Bill, rule: AttributeRule, result: DetectorResult
) -> tuple[list[Entry], list[tuple[Entry, Found]]]:
    """Trigger positions without the attribute, and those that state it (with the match)."""
    missing: list[Entry] = []
    stated: list[tuple[Entry, Found]] = []
    for item in bill.items:
        if not _triggered(rule, item):
            continue
        result.count(TRIGGER_ITEMS)
        if any(_holds(condition, item, item.short) for condition in rule.excludes):
            result.count(TRIGGERS_EXCLUDED)
            continue
        found = search(rule.attribute_pattern, item.text)
        if found is None or (
            rule.open_pattern is not None and search(rule.open_pattern, item.text) is not None
        ):
            missing.append(item)
        else:
            result.count(TRIGGERS_WITH_ATTRIBUTE)
            stated.append((item, found))
    return missing, stated


def _triggered(rule: AttributeRule, item: Entry) -> bool:
    short = item.short
    if rule.ignore_in_description:
        for found in search_all(rule.ignore_in_description, short):
            short = short[: found.start] + " " * (found.end - found.start) + short[found.end :]
    return any(all(_holds(c, item, short) for c in conditions) for conditions in rule.triggers)


def _holds(condition: TextCondition, item: Entry, short: str) -> bool:
    if condition.part is TextPart.DESCRIPTION:
        text = short
    elif condition.part is TextPart.LONG_DESCRIPTION:
        text = item.long
    else:
        text = f"{short}\n{item.long}" if item.long else short
    if not text.strip():
        return False
    found = search_start if condition.at_start else search
    return found(condition.pattern, text) is not None


def _neighbour(
    missing: list[Entry], stated: list[tuple[Entry, Found]]
) -> tuple[Entry, Found] | None:
    """A position of the same section as a listed one that states the attribute."""
    for entry in missing:
        if entry.section is None:
            continue
        for other, found in stated:
            if other.table is entry.table and other.section == entry.section:
                return other, found
    return None
