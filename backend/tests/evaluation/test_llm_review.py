"""Scoring the sandwich review against answer keys, on invented bills the tests write."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.agents.bill_review import Issue, PartResult, Review, rank
from app.evaluation import llm_review
from app.evaluation.llm_review import (
    Check,
    main,
    model_findings,
    ordered,
    ranked,
    run_stats,
    score,
    together,
)

from tests.support.made_up_bills import long_bill, practice_folder


def _planted(error_id: str, oz: str, row: int, *rows: int) -> dict[str, object]:
    return {
        "error_id": error_id,
        "oz": oz,
        "row": row,
        "rows": [row, *rows],
        "kind": "made_up",
        "finding_category": "error",
    }


# An invented answer key for the scoring functions: four planted faults (pf-01 also lists its
# neighbour row 31), an oddity the original already had and a position that must not be flagged.
KEY = {
    "planted": [
        _planted("pf-01", "01.02.0001", 30, 31),
        _planted("pf-05", "03.02.0011", 91),
        _planted("pf-13", "05.02.0012", 186),
        _planted("pf-20", "08.01.0001", 292),
    ],
    "not_planted": [{"id": "orig-17", "kind": "pipe lengths", "rows": [292, 293]}],
    "must_not_flag": [{"id": "ok-1", "rows": [48], "positions": ["02.01.0002"]}],
}


def _issue(oz: str, rows: tuple[int, ...], *, category: str | None = None) -> Issue:
    return Issue(
        part=1,
        oz=oz,
        row_numbers=rows,
        issue_type="018",
        issue_name="Decimal point error",
        category=category,
        quote="2650",
        grounded=True,
        why="Quantity one digit short.",
        related_oz=(),
    )


def _review(*issues: Issue) -> Review:
    part = PartResult(part=1, section="03", positions=[], prompt_chars=10, seconds=1.0)
    part.issues = list(issues)
    return Review("test", "bill", [part], 10)


def test_a_planted_fault_is_found_when_an_issue_names_one_of_its_rows() -> None:
    review = _review(
        _issue("03.02.0011", (91,), category="error"),  # pf-05, its own row
        _issue("01.02.0002", (31,)),  # pf-01 lists the neighbour rows too
        _issue("02.01.0002", (48,)),  # a position that must not be flagged
        _issue("03.02.0001", (81,)),  # not in the key
    )
    s = score(review, KEY)
    by_id = {p["id"]: p for p in s["planted"]}
    assert (s["planted_found"], s["planted_localized"], s["planted_category_match"]) == (2, 1, 1)
    assert by_id["pf-05"]["localized"] and by_id["pf-05"]["issue"]["oz"] == "03.02.0011"
    assert by_id["pf-01"]["found"] and not by_id["pf-01"]["localized"]
    assert s["planted_found_specific"] is None  # no control run
    assert (s["issues"], s["issues_on_keyed_rows"], s["issues_unmatched"]) == (4, 2, 2)
    assert [t["oz"] for t in s["traps"]] == ["02.01.0002"]


def test_the_checks_and_the_model_are_scored_alone_together_and_as_a_ranked_list() -> None:
    review = _review(
        _issue("03.02.0011", (91,)),  # pf-05
        _issue("05.02.0012", (186,)),  # pf-13
        _issue("08.01.0001", (292,)),  # pf-20, which the checks find too (and orig-17)
        _issue("02.01.0002", (48,)),  # a position that must not be flagged
    )
    checks = [Check("deterministic.line_total/line_total_mismatch", "high", "Line total", (292,))]
    suggestions = rank(review, checked={"08.01.0001"})
    t = together(review, checks, suggestions, KEY, top=2)
    assert t["checks"] == {
        "planted_found": 1,
        "found": ["pf-20"],
        "oddities_found": 1,  # 08.01.0001 is part of a real oddity too (pipe lengths)
        "oddities": ["orig-17"],
        "findings": 1,
    }
    assert t["model"]["found"] == ["pf-05", "pf-13", "pf-20"]
    assert t["together"]["only_model"] == ["pf-05", "pf-13"]
    assert t["together"]["missed"] == ["pf-01"]
    # the checks and the first two suggestions on positions they do not flag (02.01, 03.02)
    assert (t["checks_and_top"]["found"], t["checks_and_top"]["items"]) == (["pf-05", "pf-20"], 3)
    r = ranked(suggestions, KEY, top=3)
    assert (r["suggestions"], r["on_unchecked_positions"]) == (4, 3)
    assert [(x["oz"], x["planted"], x["trap"]) for x in r["top"]] == [
        ("02.01.0002", [], True),
        ("03.02.0011", ["pf-05"], False),
        ("05.02.0012", ["pf-13"], False),
    ]
    assert (r["top_planted"], r["top_oddities"], r["top_traps"]) == (2, 0, 1)


def test_a_fault_whose_position_is_flagged_on_the_clean_bill_too_is_not_specific() -> None:
    review = _review(_issue("03.02.0011", (91,)), _issue("05.02.0012", (186,)))
    control = _review(_issue("03.02.0011", (91,)))
    s = score(review, KEY, control)
    assert (s["planted_found"], s["planted_found_specific"]) == (2, 1)
    assert {p["id"] for p in s["planted"] if p["flagged_in_clean"]} == {"pf-05"}


def test_run_statistics_count_rejections_by_reason() -> None:
    review = _review()
    review.parts[0].error = "TimeoutError: x"
    stats = run_stats(review)
    assert (stats["parts"], stats["parts_failed"], stats["errors"]) == (
        1,
        1,
        ["part 1: TimeoutError: x"],
    )


def test_a_dry_run_builds_every_prompt_and_writes_the_report(tmp_path: Path) -> None:
    faulty, _, key = long_bill(tmp_path / "bill")
    out = tmp_path / "out"
    code = main(
        [
            "--bill",
            str(faulty),
            "--answer-key",
            str(key),
            "--out",
            str(out),
            "--parts",
            "1,2",
            "--split-by-section",  # the earlier design: one question per section
            "--issue-types",
            "081,080,018,051,031",
            "--dry-run",
        ]
    )
    assert code == 0
    result = json.loads((out / "results.json").read_text("utf-8"))
    assert [p["part"] for p in result["parts"]] == [1, 2]
    assert result["score"]["planted_found"] == 0
    assert "Planted faults found | 0 of 3" in (out / "report.md").read_text("utf-8")
    prompt = (out / "prompts" / "bill-part-1.txt").read_text("utf-8")
    assert prompt.index("THE WHOLE BILL") < prompt.index("THE PART TO CHECK")


class _FakeModel:
    """Stands in for the Ollama generator: flags the first position of every part."""

    def __init__(self, settings: object, num_gpu: int | None) -> None:
        self.num_gpu = num_gpu
        self.last_usage: tuple[int | None, int | None] = (1000, 50)

    def __call__(self, prompt: str) -> str:
        part = prompt[prompt.index("<part>") :]
        oz = part.split("Position ", 1)[1].split()[0]
        return json.dumps({"issues": [{"oz": oz, "issue_type": "031", "why": "Vague."}]})


def test_a_run_with_a_model_scores_the_bill_and_the_clean_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("app.evaluation.llm_review._Generator", _FakeModel)
    faulty, clean, key = long_bill(tmp_path / "bill")
    out = tmp_path / "out"
    code = main(
        [
            "--bill",
            str(faulty),
            "--answer-key",
            str(key),
            "--clean",
            str(clean),
            "--out",
            str(out),
            "--parts",
            "3",
            "--num-gpu",
            "0",
            "--split-by-section",
            "--issue-types",
            "081,080,018,051,031",
        ]
    )
    assert code == 0
    result = json.loads((out / "results.json").read_text("utf-8"))
    # part 3 is section 03, part 1 of 3: Titel 03.01, its first position not keyed
    assert result["issue_types"] == {"single": ["081", "080", "018", "051", "031"]}
    assert result["score"]["issues"] == 1
    assert result["score"]["planted_found"] == 0
    assert result["control"]["issues"] == 1
    assert result["stats"]["prompt_tokens_max"] == 1000
    assert "bill part 3 (03 (1 of 3)): 1 issues" in capsys.readouterr().out
    answered = (out / "parts.jsonl").read_text("utf-8").splitlines()
    assert [json.loads(line)["bill"] for line in answered] == ["bill", "clean"]
    # the default reading list comes with every bill: the checks by their measured rule rate
    assert {e["stage"] for e in result["reading_list"]} <= {
        "proven",
        "measured",
        "unmeasured",
        "model",
    }
    assert result["reading_list"] and isinstance(result["worth_a_look"], list)


def test_the_generator_can_keep_the_model_off_the_gpu() -> None:
    from app.core.config import LLMSettings
    from app.evaluation.llm_review import _Generator

    settings = LLMSettings(provider="ollama", model="qwen2.5:7b-instruct")
    assert _Generator(settings, 0)._options["num_gpu"] == 0
    assert "num_gpu" not in _Generator(settings, None)._options


def test_the_hosted_generator_sends_the_prompt_and_retries_a_rate_limit() -> None:
    import httpx

    from app.evaluation.llm_review import _OpenAIGenerator

    seen: list[httpx.Request] = []
    replies = iter(
        [
            httpx.Response(429, json={"error": {"code": "rate_limit_exceeded"}}),
            httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": '{"issues": []}'}}],
                    "usage": {"prompt_tokens": 1200, "completion_tokens": 30},
                },
            ),
            httpx.Response(401, json={"error": {"code": "invalid_api_key", "message": "sk-x"}}),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(replies)

    waits: list[float] = []
    generate = _OpenAIGenerator(
        base_url="https://api.example.test/v1/",
        model="some-model",
        api_key="secret",
        max_output_tokens=4000,
        timeout=30,
        reasoning_effort="low",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=waits.append,
    )
    assert generate("Check this. Answer only with JSON.") == '{"issues": []}'
    assert generate.last_usage == (1200, 30)
    assert waits == [5]
    body = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://api.example.test/v1/chat/completions"
    assert seen[0].headers["Authorization"] == "Bearer secret"
    assert body["model"] == "some-model"
    assert body["response_format"] == {"type": "json_object"}
    assert (body["max_completion_tokens"], body["reasoning_effort"]) == (4000, "low")
    assert "temperature" not in body
    assert body["messages"] == [{"role": "user", "content": "Check this. Answer only with JSON."}]
    with pytest.raises(RuntimeError, match=r"^status 401 \(invalid_api_key\)$"):
        generate("again")


def test_the_hosted_generator_does_not_retry_an_empty_credit_balance() -> None:
    import httpx

    from app.evaluation.llm_review import _OpenAIGenerator

    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, json={"error": {"code": "credit_balance_exhausted"}})

    generate = _OpenAIGenerator(
        base_url="https://api.example.test/v1",
        model="some-model",
        api_key="secret",
        max_output_tokens=100,
        timeout=30,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _seconds: None,
    )
    with pytest.raises(RuntimeError, match=r"status 429 \(credit_balance_exhausted\)"):
        generate("x")
    assert len(calls) == 1


def test_an_answer_cut_off_by_the_output_limit_is_reported_as_such() -> None:
    import httpx

    from app.evaluation.llm_review import _OpenAIGenerator

    def handler(request: httpx.Request) -> httpx.Response:
        choice = {"message": {"content": ""}, "finish_reason": "length"}
        return httpx.Response(200, json={"choices": [choice], "usage": {}})

    generate = _OpenAIGenerator(
        base_url="https://api.example.test/v1",
        model="some-model",
        api_key="secret",
        max_output_tokens=100,
        timeout=30,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(RuntimeError, match="output limit was used up"):
        generate("x")


def test_the_hosted_provider_needs_a_model_and_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    faulty, _, key = long_bill(tmp_path / "bill")
    common = [
        "--bill",
        str(faulty),
        "--answer-key",
        str(key),
        "--out",
        str(tmp_path / "out"),
        "--provider",
        "openai",
        "--split-by-section",
    ]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="needs --model"):
        main(common)
    with pytest.raises(SystemExit, match="OPENAI_API_KEY is not set"):
        main([*common, "--model", "some-model"])
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    made: list[dict[str, object]] = []

    class _Hosted:
        def __init__(self, **options: object) -> None:
            made.append(options)
            self.last_usage: tuple[int | None, int | None] = (10, 2)

        def __call__(self, prompt: str) -> str:
            return '{"issues": []}'

    monkeypatch.setattr("app.evaluation.llm_review._OpenAIGenerator", _Hosted)
    assert main([*common, "--model", "some-model", "--parts", "13"]) == 0
    assert made[0]["base_url"] == "https://api.openai.com/v1"
    assert made[0]["api_key"] == "secret"
    result = json.loads((tmp_path / "out" / "results.json").read_text("utf-8"))
    assert (result["provider"], result["model"]) == ("openai", "some-model")
    # requests at the same time: every pass at once, the parts still in bill order
    many = ["--model", "some-model", "--passes", "numbers,missing", "--workers", "3"]
    assert main([*common, *many, "--parts", "11,12,13"]) == 0
    result = json.loads((tmp_path / "out" / "results.json").read_text("utf-8"))
    assert [(p["focus"], p["part"]) for p in result["parts"]] == [
        ("numbers", 11),
        ("numbers", 12),
        ("numbers", 13),
        ("missing", 11),
        ("missing", 12),
        ("missing", 13),
    ]
    assert result["together"]["checks"]["findings"] > 0  # the app's checks ran on the bill
    local = [a for a in common if a not in ("--provider", "openai")]
    with pytest.raises(SystemExit, match="--workers above 1 needs a hosted provider"):
        main([*local, "--workers", "2"])


def test_a_review_in_passes_asks_every_section_once_per_pass_and_scores_them_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def answer(prompt: str) -> str:
        task = prompt[prompt.index("YOUR TASK") :]
        asked.append(task)
        if "018 Decimal point error" in task and "section 03, positions 03.02" in task:
            return json.dumps({"issues": [{"oz": "03.02.0011", "issue_type": "018", "why": "x"}]})
        return EMPTY

    class _Model:
        def __init__(self, settings: object, num_gpu: int | None) -> None:
            self.last_usage: tuple[int | None, int | None] = (100, 5)

        def __call__(self, prompt: str) -> str:
            return answer(prompt)

    monkeypatch.setattr("app.evaluation.llm_review._Generator", _Model)
    faulty, _, key = long_bill(tmp_path / "bill")
    out = tmp_path / "out"
    args = [
        "--bill",
        str(faulty),
        "--answer-key",
        str(key),
        "--out",
        str(out),
        "--parts",
        "4",
        "--split-by-section",
    ]
    with pytest.raises(SystemExit, match="unknown passes: nope"):
        main([*args, "--passes", "numbers,nope"])
    assert main([*args, "--passes", "numbers,missing"]) == 0
    assert len(asked) == 2  # part 4 (section 03, part 2 of 3) once per pass
    assert "- 016 Incorrect quantity calculation: the quantity does not follow" in asked[0]
    assert "- 133 Incomplete work package:" in asked[1]
    result = json.loads((out / "results.json").read_text("utf-8"))
    assert list(result["issue_types"]) == ["numbers", "missing"]
    assert [p["focus"] for p in result["parts"]] == ["numbers", "missing"]
    assert result["score"]["planted_found"] == 1  # pf-05
    assert result["by_pass"]["numbers"]["found"] == ["pf-05"]
    assert result["by_pass"]["missing"]["planted_found"] == 0
    assert result["stats"]["prompt_tokens_total"] == 200
    assert (out / "prompts" / "bill-missing-part-1.txt").exists()


EMPTY = '{"issues": []}'


def test_the_checks_and_the_model_take_turns_in_one_reading_list() -> None:
    review = _review(_issue("03.02.0011", (91,)), _issue("05.02.0012", (186,)))
    model = model_findings(rank(review))
    assert [(f.detector_id, sorted(f.rows)) for f in model] == [
        ("model.sandwich", [91]),
        ("model.sandwich", [186]),
    ]
    checks = [*model_findings(rank(_review(_issue("01.01.0001", (5,)))))] * 3
    assert [sorted(f.rows) for f in ordered("interleaved", checks, model)] == [
        [5],
        [91],
        [5],
        [186],
        [5],
    ]
    assert ordered("checks_then_model", checks, model)[3:] == model
    assert ordered("model", checks, model) == model


def test_the_practice_benchmark_scores_every_bill_and_reading_list(tmp_path: Path) -> None:
    practice = practice_folder(tmp_path / "practice")
    out = tmp_path / "out"
    every = ["--passes", "all", "--judge", "--dry-run"]
    assert main(["--practice", str(practice), "--out", str(out), *every]) == 0
    result = json.loads((out / "practice.json").read_text("utf-8"))
    assert (result["planted"], len(result["variants"]), len(result["clean_findings"])) == (
        24,
        8,
        4,
    )
    totals = result["totals"]
    assert list(totals) == [
        "checks",
        "model",
        "checks_then_model",
        "interleaved",
        "judged",
        "reading_list",
    ]
    # the default list without a model: the proven checks, then the others by their held-out
    # rule rate (rules below the cut only worth a look), so shorter than the checks alone
    assert totals["reading_list"]["findings"] < totals["checks"]["findings"]
    assert (out / "worth-a-look.jsonl").read_text("utf-8").strip()
    assert totals["checks"]["f2_at_50"] > 0.4  # the checks alone, without a model
    assert totals["model"]["found"] == 0  # a dry run asks no model
    assert totals["interleaved"]["found"] == totals["checks"]["found"]
    # without answers every disputed claim stays unsure: the judged list is the checks, the
    # proven ones first and one finding per row set
    assert totals["judged"]["found"] == totals["checks"]["found"]
    assert totals["judged"]["findings"] < totals["checks"]["findings"]
    judge = result["judge"]
    assert judge["requests"] > 0 and judge["stages"]["proven"] > 0
    assert set(judge["faulty"]) == {"all/unsure", "checks/unsure"}
    assert set(totals["checks"]["by_difficulty"]) == {"easy", "medium", "hard"}
    assert all(v["matches_key"] for v in result["variants"].values())
    report = (out / "practice.md").read_text("utf-8")
    assert "| The app's checks alone |" in report
    assert "## The judge: disputed claims by verdict" in report
    ablation = json.loads((out / "ablation.json").read_text("utf-8"))
    variants = ablation["variants"]
    assert len(ablation["bills"]) == 8 and "no_text" in variants
    assert variants["default"]["f2_at_50"] == pytest.approx(totals["reading_list"]["f2_at_50"])
    assert variants["no_model"]["f2_at_50"] == pytest.approx(variants["default"]["f2_at_50"])
    assert "| Without the model's claims (checks only) |" in (out / "ablation.md").read_text(
        "utf-8"
    )
    with pytest.raises(SystemExit, match="--practice FOLDER"):
        main(["--out", str(out)])


def test_a_practice_run_on_some_bills_ranks_the_checks_as_a_full_run_does(tmp_path: Path) -> None:
    practice = practice_folder(tmp_path / "practice")

    def default_list(out: Path, *more: str) -> dict[str, float]:
        assert main(["--practice", str(practice), "--out", str(out), "--dry-run", *more]) == 0
        result = json.loads((out / "practice.json").read_text("utf-8"))
        return {
            bill: v["orders"]["reading_list"]["before"]["f2_at_50"]
            for bill, v in result["variants"].items()
        }

    every = default_list(tmp_path / "all")
    some = default_list(tmp_path / "a", "--bills", "alpha-*")
    assert set(some) == {"alpha-v1", "alpha-v2"}
    assert some == {bill: every[bill] for bill in some}  # rates from the checks of every bill
    with pytest.raises(SystemExit, match="no faulty bill matches"):
        main(["--practice", str(practice), "--out", str(tmp_path / "x"), "--bills", "nothing"])


def test_the_mechanism_lists_proven_then_agreed_then_judge_confirmed_findings() -> None:
    from app.agents.bill_review import JudgedPart, Verdict
    from app.evaluation.answer_key import Checked
    from app.evaluation.llm_review import mechanism
    from app.evaluation.scoring import Finding
    from tests.unit.agents.test_bill_review import _bill

    bill = _bill()  # positions 01.01.0001-0005 on rows 4-8, 01.02.0001 on row 11

    def check(issue_id: str, *rows: int) -> Finding:
        return Finding(
            issue_id, "domain.x", "rule", "low", f"check {issue_id}", frozenset(rows), frozenset()
        )

    checked = Checked(
        findings=[
            check("line", 4),
            check("soft-agreed", 5),
            check("soft-alone", 6),
        ],
        identities={},
        dataset=None,
        status="ok",
    )
    suggestions = rank(
        _review(
            _issue("01.01.0001", (4,)),  # agreed with a proven check: listed once
            _issue("01.01.0002", (5,)),  # agreed with a soft check
            _issue("01.01.0004", (7,)),
            _issue("01.02.0001", (11,)),
        )
    )
    asked: list[list[str]] = []

    def judge(claims: list[object]) -> list[JudgedPart]:
        asked.append([f"{c.cid}:{c.source}:{c.oz}" for c in claims])  # type: ignore[attr-defined]
        part = JudgedPart(1, "01", [], 0, 0.0)
        part.verdicts = [
            Verdict("C1", "rejected", "", "", False),  # soft-alone
            Verdict("C2", "confirmed", "", "", True),  # model on row 7
        ]
        return [part]

    judged = mechanism(bill, checked, frozenset({"line"}), suggestions, judge)
    assert asked == [["C1:checks:01.01.0003", "C2:model:01.01.0004", "C3:model:01.02.0001"]]
    assert [sorted(f.rows) for f in judged.findings] == [[4], [5], [7], [11]]
    assert judged.stages == {"proven": 1, "agreed": 1, "confirmed": 1, "unsure": 1}
    assert {c["cid"]: c["verdict"] for c in judged.claims} == {
        "C1": "rejected",
        "C2": "confirmed",
        "C3": "unsure",
    }


def test_the_high_certainty_design_judges_every_unproven_check_and_every_high_claim() -> None:
    from dataclasses import replace as changed

    from app.agents.bill_review import JudgedPart, Verdict
    from app.evaluation.answer_key import Checked
    from app.evaluation.llm_review import mechanism_high
    from app.evaluation.scoring import Finding
    from tests.unit.agents.test_bill_review import _bill

    bill = _bill()  # positions 01.01.0001-0005 on rows 4-8, 01.02.0001 on row 11

    def check(issue_id: str, *rows: int) -> Finding:
        return Finding(
            issue_id, "domain.x", "rule", "low", f"check {issue_id}", frozenset(rows), frozenset()
        )

    checked = Checked(
        findings=[check("line", 4), check("soft-agreed", 5), check("soft-alone", 6)],
        identities={},
        dataset=None,
        status="ok",
    )
    suggestions = rank(
        _review(
            changed(_issue("01.01.0001", (4,)), certainty="high"),
            changed(_issue("01.01.0002", (5,)), certainty="low"),  # agrees with a soft check
            changed(_issue("01.01.0004", (7,)), certainty="high"),
            changed(_issue("01.02.0001", (11,)), certainty="medium"),
        )
    )
    asked: list[list[str]] = []

    def judge(claims: list[object]) -> list[JudgedPart]:
        asked.append([f"{c.cid}:{c.source}:{c.oz}" for c in claims])  # type: ignore[attr-defined]
        part = JudgedPart(1, "whole bill", [], 0, 0.0)
        part.verdicts = [
            Verdict("C1", "rejected", "", "", False),  # soft-agreed: still listed as agreed
            Verdict("C2", "confirmed", "", "", True),  # soft-alone
            Verdict("C4", "confirmed", "", "", True),  # the high claim on row 7
        ]
        return [part]

    judged, look = mechanism_high(bill, checked, frozenset({"line"}), suggestions, judge)
    assert asked == [
        [
            "C1:checks:01.01.0002",
            "C2:checks:01.01.0003",
            "C3:model:01.01.0001",
            "C4:model:01.01.0004",
        ]
    ]
    assert [sorted(f.rows) for f in judged.findings] == [[4], [6], [5], [7]]
    assert judged.stage_of == ["proven", "confirmed", "agreed", "confirmed"]
    assert sorted(s.oz for s in look) == ["01.01.0002", "01.02.0001"]
    by_cid = {c["cid"]: (c["verdict"], c["agreed"], c["certainty"]) for c in judged.claims}
    assert by_cid == {
        "C1": ("rejected", True, None),
        "C2": ("confirmed", False, None),
        "C3": ("unsure", True, "high"),
        "C4": ("confirmed", False, "high"),
    }


def test_the_anthropic_provider_needs_a_model_and_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    practice = tmp_path / "practice"  # never read: the settings are checked first
    base = ["--practice", str(practice), "--out", str(tmp_path), "--provider", "anthropic"]
    with pytest.raises(SystemExit, match="needs --model"):
        main(base)
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY is not set"):
        main([*base, "--model", "claude-haiku-5-5"])
    with pytest.raises(SystemExit, match="--judge-model needs --provider anthropic"):
        main(["--practice", str(practice), "--out", str(tmp_path), "--judge-model", "x"])


def test_load_dotenv_sets_only_missing_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n\nANTHROPIC_API_KEY=\"from-file\"\nexport OTHER_NAME='two'\n"
        "SET_ALREADY=file\nEMPTY=\nno equals sign\n",
        encoding="utf-8",
    )
    for name in ("ANTHROPIC_API_KEY", "OTHER_NAME", "EMPTY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SET_ALREADY", "shell")

    assert llm_review.load_dotenv(env) == ["ANTHROPIC_API_KEY", "OTHER_NAME"]
    assert os.environ["ANTHROPIC_API_KEY"] == "from-file"
    assert os.environ["OTHER_NAME"] == "two"
    assert os.environ["SET_ALREADY"] == "shell"
    assert "EMPTY" not in os.environ
    assert llm_review.load_dotenv(tmp_path / "missing.env") == []
