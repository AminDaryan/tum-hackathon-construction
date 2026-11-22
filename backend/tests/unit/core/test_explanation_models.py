"""Problems and explanations: the shapes later steps compute and store, and their rules."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.explanation import (
    MAX_TEXT_BYTES,
    Claim,
    Explanation,
    ExplanationStatus,
    capped,
)
from app.models.problem import AnomalyType, Problem, ProblemLink, ProblemLinkKind
from tests.unit.repositories.samples import T0, make_explanation


def _problem(**changes: object) -> Problem:
    data: dict[str, object] = {
        "problem_id": "prb_line_total_1",
        "issue_ids": ["iss_1", "iss_2"],
        "primary_issue_id": "iss_1",
        "links": [
            ProblemLink(
                kind=ProblemLinkKind.CARRIED_DIFFERENCE,
                from_issue_id="iss_1",
                to_issue_id="iss_2",
                detail="The line total's difference is carried into the subtotal.",
            )
        ],
        "anomaly_type": AnomalyType.LOGICAL,
        "money_at_stake": Decimal("112.50"),
        "currency": "EUR",
        "title": "Line total does not match quantity × unit price",
    }
    data.update(changes)
    return Problem.model_validate(data)


class TestProblem:
    def test_the_seven_anomaly_types(self) -> None:
        assert [t.value for t in AnomalyType] == [
            "price",
            "quantity",
            "unit",
            "semantic",
            "structural",
            "logical",
            "duplicate",
        ]
        assert [k.value for k in ProblemLinkKind] == [
            "same_cell",
            "same_row",
            "carried_difference",
            "same_group",
        ]

    def test_a_valid_problem_round_trips(self) -> None:
        problem = _problem()
        assert Problem.model_validate_json(problem.model_dump_json()) == problem
        assert problem.money_at_stake == Decimal("112.50")
        assert problem.model_dump(mode="json")["money_at_stake"] == "112.50"  # exact, no float

    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            ({"issue_ids": []}, "at least 1 item"),
            ({"issue_ids": ["iss_1", "iss_1"]}, "each finding once"),
            ({"primary_issue_id": "iss_9"}, "primary finding"),
            (
                {
                    "links": [
                        {
                            "kind": "same_row",
                            "from_issue_id": "iss_1",
                            "to_issue_id": "iss_9",
                            "detail": "x",
                        }
                    ]
                },
                "only join findings",
            ),
            ({"currency": None}, "needs its currency"),
            ({"money_at_stake": None}, "needs its currency"),
            ({"currency": "eur"}, "pattern"),
            ({"money_at_stake": "NaN"}, ""),
            ({"anomaly_type": "typo"}, ""),
            ({"problem_id": "has space"}, "pattern"),
            ({"title": ""}, ""),
        ],
    )
    def test_invalid_problems(self, changes: dict[str, object], message: str) -> None:
        with pytest.raises(ValidationError, match=message or None):
            _problem(**changes)

    def test_without_money_at_stake(self) -> None:
        problem = _problem(money_at_stake=None, currency=None, links=[])
        assert problem.money_at_stake is None and problem.currency is None

    def test_a_link_joins_two_findings(self) -> None:
        with pytest.raises(ValidationError, match="two different findings"):
            ProblemLink(kind="same_cell", from_issue_id="iss_1", to_issue_id="iss_1", detail="x")


class TestExplanation:
    def test_every_status_round_trips(self) -> None:
        for status in ExplanationStatus:
            explanation = make_explanation(status=status)
            assert Explanation.model_validate_json(explanation.model_dump_json()) == explanation

    def test_status_rules(self) -> None:
        done = make_explanation()
        with pytest.raises(ValidationError, match="finished_at is set exactly"):
            done.evolve(finished_at=None)
        with pytest.raises(ValidationError, match="finished_at is set exactly"):
            done.evolve(status=ExplanationStatus.RUNNING)
        with pytest.raises(ValidationError, match="cannot precede"):
            done.evolve(finished_at=T0 - timedelta(seconds=1))
        with pytest.raises(ValidationError, match="error is set exactly"):
            done.evolve(error="Timed out.")
        with pytest.raises(ValidationError, match="error is set exactly"):
            make_explanation(status=ExplanationStatus.FAILED).evolve(error=None)
        queued = make_explanation(status=ExplanationStatus.QUEUED)
        claim = Claim(section="summary", text="x", rendered="x")
        with pytest.raises(ValidationError, match="no claims and no output"):
            queued.evolve(claims=[claim])
        with pytest.raises(ValidationError, match="no claims and no output"):
            queued.evolve(raw_output="{}")
        assert queued.evolve(prompt="Erkläre …").prompt == "Erkläre …"  # a prompt may be stored

    def test_claims(self) -> None:
        with pytest.raises(ValidationError):
            Claim(section="details", text="x", rendered="x")  # type: ignore[arg-type]  # unknown section, on purpose
        with pytest.raises(ValidationError):
            Claim(section="summary", text="", rendered="x")

    def test_prompt_and_output_are_capped_at_64_kib(self) -> None:
        assert MAX_TEXT_BYTES == 65_536
        done = make_explanation()
        at_cap = "x" * MAX_TEXT_BYTES
        assert done.evolve(prompt=at_cap, raw_output=at_cap).prompt == at_cap
        for field in ("prompt", "raw_output"):
            with pytest.raises(ValidationError, match="shorten it with capped"):
                done.evolve(**{field: at_cap + "x"})
        umlauts = "ä" * (MAX_TEXT_BYTES // 2 + 1)  # two bytes each: one byte over the cap
        with pytest.raises(ValidationError):
            done.evolve(prompt=umlauts)
        assert done.evolve(prompt=capped(umlauts)).prompt is not None


class TestCapped:
    def test_short_texts_are_unchanged(self) -> None:
        assert capped("Grüße", 100) == "Grüße"
        assert capped("x" * MAX_TEXT_BYTES) == "x" * MAX_TEXT_BYTES

    def test_long_texts_are_cut_at_a_character_boundary(self) -> None:
        text = "ä" * 100  # 200 bytes
        cut = capped(text, 51)
        assert cut.endswith("\n[truncated]")
        assert len(cut.encode("utf-8")) <= 51
        assert cut.removesuffix("\n[truncated]") == "ä" * 19  # 39 bytes leave 19 whole "ä"
        assert len(capped("x" * (MAX_TEXT_BYTES + 5)).encode("utf-8")) == MAX_TEXT_BYTES

    def test_the_limit_must_hold_the_mark(self) -> None:
        with pytest.raises(ValueError, match="at least"):
            capped("x" * 100, 5)
