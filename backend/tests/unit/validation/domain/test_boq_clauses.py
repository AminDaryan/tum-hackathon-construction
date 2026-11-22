"""domain.boq_clauses: clauses in the bill texts that a bidder must price or ask about.

The texts are short synthetic German sentences in the wording of real bills."""

from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from app.models.dataset import RowKind
from app.models.issue import EvidenceClass, Severity
from app.validation.domain.boq.clauses import (
    CATEGORY_CLAUSE,
    CATEGORY_DOCUMENT,
    CATEGORY_LUMP_SUM,
    CATEGORY_WORDING,
    ITEMS_READ,
    RULE_ASSUMED,
    RULE_DEFERRED,
    RULE_DOCUMENT,
    RULE_LUMP_SUM,
    RULE_RISK,
    RULE_VAGUE,
    SENTENCES_IN_WINDOWS,
    SKIPPED_ON_TOKENS,
    BoqClausesConfig,
    BoqClausesDetector,
)
from tests.support.builders import DatasetBuilder
from tests.unit.validation.deterministic.references_fixtures import (
    LARGE_ROWS,
    applicability,
    assert_unique_fingerprints,
    assert_well_formed,
    by_rule,
    large_boq_dataset,
    run,
    run_pipeline,
)

DETECTOR = BoqClausesDetector
COLUMNS = [
    ("Pos.", "item_code"),
    ("Kurztext", "description"),
    ("Langtext", "long_description"),
    ("Menge", "quantity"),
    ("ME", "unit"),
    ("EP", "unit_price"),
]
# A tender exported to Excel: no long text column and no unit price.
TENDER_COLUMNS = [
    ("Pos.", "item_code"),
    ("Kurztext", "description"),
    ("Menge", "quantity"),
    ("ME", "unit"),
]


def item(code, short, long=None, unit="m3", price="10.00"):
    return [code, short, long, "5", unit, price]


def dataset(profile, rows, columns=COLUMNS):
    builder = DatasetBuilder(profile)
    table = builder.table("LV", columns)
    for values in rows:
        table.row(values)
    return builder.build()


def result(profile, rows, overrides=None):
    return run(DETECTOR, dataset(profile, rows), profile, overrides)


def subject(issue):
    """The subject a grouped finding is about, from its rule evidence."""
    return next(e.data["subject"] for e in issue.evidence if "subject" in e.data)


class TestRiskShiftingClauses:
    def test_one_finding_per_subject_lists_the_positions(self, boq_profile) -> None:
        rows = [
            item(
                "01.0010", "Boden lösen", "Erschwernisse durch Grundwasser sind einzukalkulieren."
            ),
            item("01.0020", "Graben ausheben", "Schichtenwasser ist in den EP einzurechnen."),
            item("01.0030", "Graben verfüllen", "Hindernisse im Boden sind mit abgegolten."),
        ]
        found = result(boq_profile, rows)
        ground, water = by_rule(found.issues, RULE_RISK)  # in the order of the subjects
        assert subject(water) == "water" and subject(ground) == "ground"
        assert (water.issue_category, water.severity) == (CATEGORY_CLAUSE, Severity.MEDIUM)
        assert water.evidence_class is EvidenceClass.SEMANTIC_WARNING
        assert "2 positions" in water.title
        assert (
            '01.0010 "Erschwernisse durch Grundwasser sind einzukalkulieren."' in water.explanation
        )
        assert "01.0020" in water.explanation
        assert {c.source.a1 for c in water.affected_cells} == {"C2", "C3"}
        assert "X ZB 7/04" in (water.suggested_action or "")
        assert "§ 7 (1) Nr. 6 VOB/A" in (water.suggested_action or "")
        assert ground.row_id is not None  # one position: the finding sits on its row
        assert_unique_fingerprints(found.issues)
        assert_well_formed(found.issues)

    def test_time_weather_and_interfaces_are_low(self, boq_profile) -> None:
        rows = [
            item("01.0010", "Pflaster", "Erschwernisse durch Witterung sind einzukalkulieren."),
            item(
                "01.0020",
                "Anschluss",
                "Leistungen anderer Gewerke sind im Einheitspreis enthalten.",
            ),
        ]
        issues = by_rule(result(boq_profile, rows).issues, RULE_RISK)
        assert {(subject(i), i.severity) for i in issues} == {
            ("time_weather", Severity.LOW),
            ("interfaces", Severity.LOW),
        }

    @pytest.mark.parametrize(
        "text",
        [
            "Grundwasser ist nicht einzukalkulieren.",
            "Die Wasserhaltung wird gesondert vergütet.",
            "Die Bodenklassen sind im LV angegeben. Kleinmaterial ist einzukalkulieren.",
            "Im Bereich Grundwasser sind einzukalkulieren: Schalung und Bewehrung.",
            "Frostschutzschicht 0/32 einbauen, Nebenleistungen sind einzukalkulieren.",
            "Bauzeitenplan beachten, Kleinmaterial ist einzukalkulieren.",
        ],
    )
    def test_clauses_that_do_not_put_a_subject_on_the_bidder(self, boq_profile, text) -> None:
        assert result(boq_profile, [item("01.0010", "Boden", text)]).issues == []

    def test_a_subject_paid_separately_does_not_count_but_the_next_one_does(
        self, boq_profile
    ) -> None:
        text = "Die Wasserhaltung wird gesondert vergütet, der Verbau ist einzukalkulieren."
        [issue] = result(boq_profile, [item("01.0010", "Graben", text)]).issues
        assert subject(issue) == "shoring"

    def test_a_list_after_a_shift_phrase_counts(self, boq_profile) -> None:
        text = "Folgende Leistungen sind einzukalkulieren: Verbau, Wasserhaltung."
        issues = result(boq_profile, [item("01.0010", "Graben", text)]).issues
        assert {subject(i) for i in issues} == {"shoring", "water"}

    def test_a_subject_far_from_the_shift_phrase_does_not_count(self, boq_profile) -> None:
        filler = ", ".join(["Rohrgraben profilgerecht herstellen"] * 4)
        text = f"Grundwasser absenken, {filler}, Kleinmaterial ist einzukalkulieren."
        assert result(boq_profile, [item("01.0010", "Graben", text)]).issues == []
        near = result(
            boq_profile, [item("01.0010", "Graben", text)], {"max_subject_gap_chars": 400}
        )
        assert [subject(i) for i in near.issues] == ["water"]

    def test_the_subject_word_list_is_configurable(self, boq_profile) -> None:
        subjects = [
            {
                "subject": "noise",
                "label": "noise protection",
                "pattern": r"\blärmschutz\b",
                "severity": "high",
            },
        ]
        text = "Lärmschutz ist einzukalkulieren, ebenso das Grundwasser."
        [issue] = result(
            boq_profile, [item("01.0010", "Graben", text)], {"risk_subjects": subjects}
        ).issues
        assert (subject(issue), issue.severity) == ("noise", Severity.HIGH)
        assert "noise protection" in issue.title


class TestAssumptionsAndDeferredDecisions:
    def test_one_finding_per_position(self, boq_profile) -> None:
        rows = [
            item(
                "01.0010",
                "Boden lösen",
                "Der Boden ist vermutlich Bodenklasse 3. Ausführung vorläufig ermittelt.",
            ),
            item("01.0020", "Leitung", "Die endgültige Festlegung der Trasse erfolgt vor Ort."),
            item(
                "01.0030", "Schacht", "Die Tiefe wird erst nach Freilegung der Leitung festgelegt."
            ),
        ]
        found = result(boq_profile, rows)
        [assumed] = by_rule(found.issues, RULE_ASSUMED)
        deferred = by_rule(found.issues, RULE_DEFERRED)
        assert assumed.title.startswith(
            "01.0010 assumes a condition: 'vermutlich' and 'vorläufig ermittelt'"
        )
        assert (assumed.severity, assumed.issue_category) == (Severity.MEDIUM, CATEGORY_CLAUSE)
        assert "§ 2 (6) VOB/B" in (assumed.suggested_action or "")
        assert sorted(i.title.split()[0] for i in deferred) == ["01.0020", "01.0030"]
        assert all(i.row_id is not None for i in found.issues)
        assert_unique_fingerprints(found.issues)
        assert_well_formed(found.issues)

    def test_plain_texts_are_not_flagged(self, boq_profile) -> None:
        rows = [
            item("01.0010", "Boden lösen", "Boden der Bodenklasse 3 lösen und seitlich lagern.")
        ]
        assert result(boq_profile, rows).issues == []


class TestVagueWording:
    def test_open_inclusions_and_details_left_open(self, boq_profile) -> None:
        rows = [
            item(
                "01.0010",
                "Rohr verlegen",
                "Rohr DN 300 verlegen, einschl. aller erforderlichen Formstücke.",
            ),
            item("01.0020", "Befestigung", "Befestigung in geeigneter Weise."),
            item("01.0030", "Pumpe", "Pumpe nach Wahl des AN."),
        ]
        [issue] = by_rule(result(boq_profile, rows).issues, RULE_VAGUE)
        assert (issue.issue_category, issue.severity) == (CATEGORY_WORDING, Severity.LOW)
        assert issue.title == "Vague wording in 3 positions"
        assert issue.explanation.count('"') == 6  # three quotes

    @pytest.mark.parametrize(
        "text",
        [
            "Rohr verlegen, einschl. aller erforderlichen Befestigungsmaterialien.",
            "Rohr verlegen, inkl. aller notwendigen Schrauben-, Dichtungs- und Befestigungsmittel.",
            "Rohr verlegen, einschl. aller erforderlichen [PERSON_074].",
            "Rohr verlegen, einschl. aller erforderlichen PER0033 Teile.",
            "Pumpe nach [PERSON_125] des AN.",
        ],
    )
    def test_small_material_and_tokens_are_not_vague(self, boq_profile, text) -> None:
        found = result(boq_profile, [item("01.0010", "Rohr", text)])
        assert by_rule(found.issues, RULE_VAGUE) == []

    @pytest.mark.parametrize(
        "text",
        [
            "Ausführung sinngemäß wie Pos. 01.0010, jedoch Abtransport zur Deponie.",
            "Sinngemäß wie Position 1.2.30, jedoch DN 200.",
            "Ausführung sinngemäß OZ 01.0010.",
        ],
    )
    def test_sinngemaess_with_the_position_it_refers_to_is_not_vague(
        self, boq_profile, text
    ) -> None:
        """It names the position meant, like "wie vor, jedoch": normal bill language."""
        found = result(boq_profile, [item("01.0050", "Rohr", text)])
        assert by_rule(found.issues, RULE_VAGUE) == []

    @pytest.mark.parametrize(
        "text",
        ["Ausführung sinngemäß.", "Anschlüsse sinngemäß herstellen, wie Pos. 01.0010."],
    )
    def test_sinngemaess_without_a_position_is_vague(self, boq_profile, text) -> None:
        found = result(boq_profile, [item("01.0050", "Rohr", text)])
        assert len(by_rule(found.issues, RULE_VAGUE)) == 1

    def test_matches_on_tokens_are_counted(self, boq_profile) -> None:
        text = "Rohr verlegen, einschl. aller erforderlichen [PERSON_074]."
        found = result(boq_profile, [item("01.0010", "Rohr", text)])
        assert found.coverage[SKIPPED_ON_TOKENS] == 1

    def test_more_positions_than_quotes_are_all_listed(self, boq_profile) -> None:
        rows = [item(f"01.00{n}0", "Pumpe", "Pumpe nach Wahl des AN.") for n in range(1, 6)]
        [issue] = result(boq_profile, rows).issues
        assert issue.explanation.count('"') == 6
        assert "All positions: 01.0010, 01.0020, 01.0030, 01.0040 and 01.0050." in issue.explanation


class TestOpenLumpSums:
    def test_a_lump_sum_billed_by_effort(self, boq_profile) -> None:
        rows = [
            item(
                "01.0010",
                "Analyse",
                "Probenahme und Analyse je Charge.",
                unit="psch",
                price="900.00",
            ),
            item(
                "01.0020", "Reinigung", "Straße reinigen nach Bedarf.", unit="psch", price="500.00"
            ),
            item("01.0030", "Reinigung", "Straße reinigen nach Bedarf.", unit="m2", price="0.50"),
        ]
        found = result(boq_profile, rows)
        [lump] = by_rule(found.issues, RULE_LUMP_SUM)
        assert (lump.issue_category, lump.severity) == (CATEGORY_LUMP_SUM, Severity.MEDIUM)
        assert "01.0010" in lump.explanation and "01.0020" in lump.explanation
        assert "01.0030" not in lump.explanation
        # "nach Bedarf" in the lump sum belongs to the lump sum finding, in the m2 item to the
        # vague wording finding.
        [vague] = by_rule(found.issues, RULE_VAGUE)
        assert "01.0030" in vague.explanation and "01.0020" not in vague.explanation

    def test_a_lump_sum_by_item_type(self, boq_profile) -> None:
        columns = [*COLUMNS, ("Positionsart", "item_type")]
        rows = [
            [
                *item(
                    "01.0010",
                    "Stundenlohnarbeiten",
                    "Abrechnung nach tatsächlichem Aufwand.",
                    unit="St",
                ),
                "Pauschalposition",
            ]
        ]
        found = run(DETECTOR, dataset(boq_profile, rows, columns), boq_profile)
        assert [i.rule_id for i in found.issues] == [RULE_LUMP_SUM]

    def test_a_scope_that_is_fixed_is_not_flagged(self, boq_profile) -> None:
        rows = [item("01.0010", "Baustelle", "Baustelleneinrichtung einrichten.", unit="psch")]
        assert result(boq_profile, rows).issues == []


class TestDocumentReferences:
    def test_references_to_plans_and_reports(self, boq_profile) -> None:
        rows = [
            item("01.0010", "Schacht", "Ausführung gemäß Zeichnung Nr. 4."),
            item("01.0020", "Boden", "Bodenklassen lt. Baugrundgutachten."),
            item("01.0030", "Leitung", "Trasse siehe Anlage 4."),
            item("01.0040", "Planum", "Planum herstellen, Höhentoleranz 2 cm."),
        ]
        [issue] = result(boq_profile, rows).issues
        assert issue.rule_id == RULE_DOCUMENT
        assert (issue.issue_category, issue.severity) == (CATEGORY_DOCUMENT, Severity.INFO)
        assert issue.evidence_class is EvidenceClass.NEEDS_EXTERNAL_CONTEXT
        assert issue.title == "3 positions refer to plans, drawings or reports"
        assert "01.0040" not in issue.explanation


def test_a_single_position_is_named_in_the_singular(boq_profile) -> None:
    rows = [
        item("01.0010", "Schacht", "Ausführung gemäß Zeichnung Nr. 4."),
        item("01.0020", "Leitung", "Einschl. aller erforderlichen Formstücke verlegen."),
        item("01.0030", "Analyse", "Probenahme und Analyse je Charge.", unit="psch"),
        item("01.0040", "Graben", "Verbau ist mit einzukalkulieren."),
    ]
    found = result(boq_profile, rows)
    [document] = by_rule(found.issues, RULE_DOCUMENT)
    assert document.title == "1 position refers to plans, drawings or reports"
    assert document.explanation.startswith(
        "1 position refers to documents that are not part of this bill, so the bill alone "
        "cannot show what it asks for: 01.0010"
    )
    [vague] = by_rule(found.issues, RULE_VAGUE)
    assert vague.explanation.startswith("1 position leaves open what is to be supplied or how")
    [lump] = by_rule(found.issues, RULE_LUMP_SUM)
    assert lump.explanation.startswith("1 lump sum depends on an amount the bill does not fix")
    [risk] = by_rule(found.issues, RULE_RISK)
    assert risk.explanation.startswith("1 position puts the cost of shoring")


class TestReading:
    def test_a_tender_without_long_text_and_prices_is_read_with_its_continuation_lines(
        self, boq_profile
    ) -> None:
        builder = DatasetBuilder(boq_profile)
        table = builder.table("LV", TENDER_COLUMNS)
        table.row(["01.0010", "Graben ausheben", "12", "m3"])
        table.row(
            [None, "Erschwernisse durch Grundwasser", None, None], kind=RowKind.TEXT, belongs_to=0
        )
        table.row([None, "sind einzukalkulieren.", None, None], kind=RowKind.TEXT, belongs_to=0)
        table.row(["01.0020", "Graben verfüllen", "12", "m3"])
        table.row(
            [None, "Verbau ist einzukalkulieren.", None, None], kind=RowKind.TEXT, belongs_to=3
        )
        found = run(DETECTOR, builder.build(), boq_profile)
        water, shoring = found.issues
        # The two lines of 01.0010 are read as one sentence; the clause is located in the line
        # its subject stands in.
        assert subject(water) == "water" and subject(shoring) == "shoring"
        assert water.explanation.startswith(
            "1 position puts the cost of water (groundwater, dewatering, surface water) into the "
            "bidder's unit prices: 01.0010 "
            '"Erschwernisse durch Grundwasser sind einzukalkulieren."'
        )
        assert {c.source.a1 for c in water.affected_cells} == {"B3"}
        assert "01.0020" in shoring.explanation
        assert {c.source.a1 for c in shoring.affected_cells} == {"B6"}
        assert found.coverage[ITEMS_READ] == 2

    def test_a_note_attached_to_an_item_is_not_read_as_its_text(self, boq_profile) -> None:
        # A GAEB "Hinweis" stands on its own even where normalization attaches it to the item
        # above; an "Unterbeschreibung" is part of the item.
        columns = [*TENDER_COLUMNS, ("Positionsart", "item_type")]
        builder = DatasetBuilder(boq_profile)
        table = builder.table("LV", columns)
        table.row(["01.0010", "Bauwerker", "60", "h", "Normalposition"])
        table.row(
            [None, "Grundwasser ist voraussichtlich einzukalkulieren.", None, None, "Hinweis"],
            kind=RowKind.TEXT,
            belongs_to=0,
        )
        table.row(["01.0020", "Graben", "60", "m3", "Normalposition"])
        table.row(
            [None, "Verbau ist einzukalkulieren.", None, None, "Unterbeschreibung"],
            kind=RowKind.TEXT,
            belongs_to=2,
        )
        found = run(DETECTOR, builder.build(), boq_profile)
        assert [subject(i) for i in found.issues] == ["shoring"]

    def test_a_clause_at_the_end_of_a_long_sentence_is_found(self, boq_profile) -> None:
        filler = ", ".join(["Rohrgraben profilgerecht herstellen und Sohle verdichten"] * 30)
        text = f"{filler}, Erschwernisse durch Grundwasser sind einzukalkulieren."
        found = result(boq_profile, [item("01.0010", "Graben", text)])
        [issue] = found.issues
        assert subject(issue) == "water"
        assert found.coverage[SENTENCES_IN_WINDOWS] == 1
        quote = issue.explanation.split('"')[1]
        assert quote.startswith("…") and quote.endswith("einzukalkulieren.") and len(quote) <= 160

    def test_long_texts_are_read_quickly(self, boq_profile) -> None:
        texts = [
            "einschl. aller erforderlichen " * 1_000,
            "a" * 30_000,
            "Grundwasser " * 2_500 + "einzukalkulieren.",
            ("Verbau, " * 40 + "ist einzukalkulieren. ") * 100,
            "nach " * 6_000,
            "[PERSON_" * 3_000,
        ]
        rows = [item(f"01.00{n}0", "Text", text) for n, text in enumerate(texts, start=1)]
        started = time.perf_counter()
        result(boq_profile, rows)
        assert time.perf_counter() - started < 5

    @pytest.mark.performance
    def test_twenty_thousand_rows_are_fast(self, boq_profile) -> None:
        dataset = large_boq_dataset(boq_profile)
        started = time.perf_counter()
        found = run(DETECTOR, dataset, boq_profile)
        assert time.perf_counter() - started < 5.0
        assert found.issues == []
        assert found.coverage[ITEMS_READ] == LARGE_ROWS

    def test_not_applicable_without_texts(self, boq_profile) -> None:
        columns = [("Pos.", "item_code"), ("Menge", "quantity"), ("ME", "unit")]
        builder = DatasetBuilder(boq_profile)
        builder.table("LV", columns).row(["01.0010", "5", "m3"])
        assert not applicability(DETECTOR, builder.build(), boq_profile).applicable

    def test_patterns_are_checked(self) -> None:
        with pytest.raises(ValidationError):
            BoqClausesConfig(shift_pattern="(")
        with pytest.raises(ValidationError):
            BoqClausesConfig(inclusion_pattern=r"einschl\.")  # no group for the first word
        with pytest.raises(ValidationError):
            BoqClausesConfig(open_detail_pattern="x?")  # matches every text


def test_findings_pass_the_pipeline_evidence_policy(boq_profile) -> None:
    rows = [
        item("01.0010", "Boden", "Grundwasser ist einzukalkulieren. Boden vermutlich BK 3."),
        item("01.0020", "Pumpe", "Pumpe nach Wahl des AN, gemäß Zeichnung."),
        item(
            "01.0030",
            "Analyse",
            "Analyse je Charge, endgültige Festlegung durch den AG.",
            unit="psch",
        ),
    ]
    outcome = run_pipeline(DETECTOR, dataset(boq_profile, rows), boq_profile)
    assert sorted(i.rule_id for i in outcome.issues) == sorted(
        [RULE_RISK, RULE_ASSUMED, RULE_VAGUE, RULE_DOCUMENT, RULE_LUMP_SUM, RULE_DEFERRED]
    )
    assert_unique_fingerprints(outcome.issues)
    assert_well_formed(outcome.issues)
