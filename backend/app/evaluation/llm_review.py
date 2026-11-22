"""Run the sandwich review (:mod:`app.agents.bill_review`) on a test bill and score it.

    python -m app.evaluation.llm_review --bill FAULTY.xlsx --answer-key KEY.json \\
        --clean ORIGINAL.xlsx --out OUT_DIR

The bill is read through the product's own upload path (security checks, extraction,
normalization, profile ``boq``) and checked by the app's own validation run (its rule checks).
Their findings go into the prompt under the positions they concern (``--no-checks`` leaves them
out). The model then reviews the bill part by part, and everything is scored against the answer
key of the BoQ test set (``Sample BoQ Dataset/Faulty Data By Claude AI``). By default the review
asks about the five issue types of ``DEFAULT_FOCUS``; ``--issue-types all`` asks about all 135;
``--passes`` asks in focused passes. ``--workers`` sends that many requests of every pass at the
same time, and all passes at once (hosted models only).

* a planted fault counts as **found** when an issue names one of its rows, as **localized** when
  it names the fault's own row, as **grounded** when that issue's quote was found in the bill;
* the **control** runs the same review on the clean bill: a planted fault whose position the
  model also flags in the clean bill is reported as found but *not specific*, because the model
  would have flagged it without the fault;
* issues on the real oddities of the original (``not_planted``) are true findings; issues on
  the positions that must not be flagged (``must_not_flag``) are false alarms; every other issue
  is *unmatched*: not in the key, for a person to judge;
* the app's checks are scored the same way, then the checks and the model together;
* the model's issues are merged and ranked by position (:func:`app.agents.bill_review.rank`), and
  the first ``--top`` suggestions are matched with the key: what a Korrektor reading the checks'
  findings and only that list would find.

``--practice FOLDER`` (instead of ``--bill`` and ``--answer-key``) runs the practice benchmark
(``Sample BoQ Dataset/Practice Benchmark P1``): every faulty bill of its ``out/`` and its clean
original are reviewed once, and the checks' findings, the model's ranked suggestions, both one
after the other and both taking turns are scored as reading lists with the shared answer-key
scorer (F2 at 50, mean over the bills, as in ``tools/practice_benchmark/run.py``). Output:
``practice.md``, ``practice.json``, ``parts.jsonl`` and ``prompts/``.

Output in ``OUT_DIR``: ``report.md`` (the summary for people), ``results.json`` (every prompt
size, raw answer, kept and rejected issue, the scores), ``parts.jsonl`` (each part as soon as it
is answered, so a long run that is stopped keeps what it has) and ``prompts/`` (the prompt of
the first part, to read what the model saw). ``--dry-run`` builds every prompt without a model.

The model is the local Ollama server by default (``--provider ollama``). ``--provider openai``
sends every prompt, and with it the bill, to a hosted model behind the OpenAI chat completions
API (``--base-url``, default ``https://api.openai.com/v1``; ``--model`` names it). Use it only for
a bill that may leave the machine. The key is read from the environment variable named by
``--api-key-env`` (default ``OPENAI_API_KEY``), never from the command line, and is never
written anywhere.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import statistics
import sys
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from itertools import zip_longest
from pathlib import Path
from typing import Any

import httpx

from app.agents.bill_review import (
    CERTAINTY,
    JUDGE_VERSION,
    PASSES,
    PROMPT_VERSION,
    VERDICTS,
    Bill,
    Claim,
    Issue,
    JudgedPart,
    PartResult,
    Rejected,
    Review,
    Suggestion,
    Verdict,
    build_prompt,
    context_layer,
    facts_from,
    judge_claims,
    load_issue_types,
    partition,
    rank,
    read_bill,
    review_bill,
)
from app.agents.claude import ClaudeGenerator
from app.agents.models import check_configured_model
from app.core.config import LLMSettings
from app.evaluation import answer_key, reading_list, review_ablation
from app.evaluation.answer_key import Checked, identities
from app.evaluation.runner import benchmark_workbench
from app.evaluation.scoring import Finding, findings_of
from app.repositories.base import IssueQuery
from app.risk.model_review import OllamaGenerator
from app.services import documents, runs

EMPTY_ANSWER = '{"issues": []}'
EMPTY_VERDICTS = '{"verdicts": []}'


class _Generator(OllamaGenerator):
    """The app's Ollama generator, with the number of layers on the GPU set per request
    (``num_gpu``; 0 runs the model on the CPU, for a machine whose GPU driver the server
    cannot use)."""

    def __init__(self, settings: LLMSettings, num_gpu: int | None) -> None:
        super().__init__(settings)
        if num_gpu is not None:
            self._options["num_gpu"] = num_gpu


class _OpenAIGenerator:
    """A hosted model behind the OpenAI chat completions API (``POST {base_url}/chat/completions``)
    with JSON answers. Rate limits and server errors are retried a few times (after the wait the
    server asks for, if it names one). Safe to call from several threads: ``last_usage`` is the
    usage of the calling thread's last request."""

    RETRY = (429, 500, 502, 503, 504)
    NO_RETRY = ("insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached")

    @staticmethod
    def _error_code(response: httpx.Response) -> str | None:
        if response.status_code == 200:
            return None
        try:
            error = response.json().get("error") or {}
        except (ValueError, AttributeError):
            return None
        code = error.get("code") or error.get("type") if isinstance(error, dict) else None
        return str(code) if code else None

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        max_output_tokens: int,
        timeout: float,
        reasoning_effort: str | None = None,
        temperature: float | None = None,
        attempts: int = 4,
        client: httpx.Client | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._body: dict[str, Any] = {
            "model": model,
            "response_format": {"type": "json_object"},
            "max_completion_tokens": max_output_tokens,
        }
        if reasoning_effort:
            self._body["reasoning_effort"] = reasoning_effort
        if temperature is not None:
            self._body["temperature"] = temperature
        self._attempts = attempts
        self._client = client or httpx.Client(timeout=timeout)
        self._sleep = sleep
        self._local = threading.local()

    @property
    def last_usage(self) -> tuple[int | None, int | None]:
        usage: tuple[int | None, int | None] = getattr(self._local, "usage", (None, None))
        return usage

    @staticmethod
    def _wait(response: httpx.Response, attempt: int) -> float:
        try:
            asked = float(response.headers.get("retry-after") or 0)
        except ValueError:
            asked = 0.0
        return min(max(asked, 5.0 * 2.0**attempt), 120.0)

    def __call__(self, prompt: str) -> str:
        body = {**self._body, "messages": [{"role": "user", "content": prompt}]}
        self._local.usage = (None, None)
        for attempt in range(self._attempts):
            response = self._client.post(self._url, json=body, headers=self._headers)
            detail = self._error_code(response)
            if (
                response.status_code not in self.RETRY
                or detail in self.NO_RETRY
                or attempt == self._attempts - 1
            ):
                break
            self._sleep(self._wait(response, attempt))
        if response.status_code != 200:
            raise RuntimeError(f"status {response.status_code} ({detail or 'no detail'})")
        data = response.json()
        usage = data.get("usage") or {}
        self._local.usage = (usage.get("prompt_tokens"), usage.get("completion_tokens"))
        choice = data["choices"][0]
        text = choice["message"].get("content")
        if not text and choice.get("finish_reason") == "length":
            raise RuntimeError("the output limit was used up before an answer (raise it)")
        if not isinstance(text, str):
            raise RuntimeError("no answer text")
        return text


# Codes after which a run stops: the account cannot pay or the key is not accepted.
STOP_CODES = (
    "insufficient_quota",
    "credit_balance_exhausted",
    "billing_hard_limit_reached",
    "authentication_error",
    "permission_error",
)


@dataclass(frozen=True, slots=True)
class Check:
    """A finding of the app's own checks (its validation run), on rows of the source file."""

    rule: str  # detector and rule, e.g. "deterministic.line_total/line_total_mismatch"
    severity: str
    title: str
    rows: tuple[int, ...]


PROVEN = "confirmed_rule_violation"  # the evidence class of a check that proves an error


def load(path: Path) -> tuple[Bill, Checked]:
    """The bill as the product reads it (upload with profile ``boq`` on in-memory storage) and
    the findings of every registered check on it, in the register's order (as the shared
    answer-key scorer's :func:`~app.evaluation.answer_key.check_file` reads them)."""
    bill, checked, _ = load_checked(path)
    return bill, checked


def load_checked(path: Path) -> tuple[Bill, Checked, frozenset[str]]:
    """:func:`load`, and the issue ids of the findings that prove an error from the bill's own
    values (evidence class ``confirmed_rule_violation``: line totals, required values)."""
    with tempfile.TemporaryDirectory(prefix="twb-llm-review-") as scratch:
        wb = benchmark_workbench(Path(scratch))
        document, dataset = documents.upload(
            wb, filename=path.name, chunks=[path.read_bytes()], profile_id="boq"
        )
        if dataset is None:
            raise SystemExit(f"{path.name}: not read ({document.processing_status.value})")
        run = runs.start(wb, dataset.dataset_id)
        with wb.uow() as uow:
            issues = list(uow.issues.iter_all(IssueQuery(run_id=run["run_id"])))
        checked = Checked(
            findings=findings_of(issues, dataset),
            identities=identities(dataset),
            dataset=dataset,
            status=document.processing_status.value,
        )
        proven = frozenset(i.issue_id for i in issues if i.effective_evidence_class.value == PROVEN)
    return read_bill(dataset, path.name), checked, proven


def checks_of(checked: Checked) -> list[Check]:
    return [
        Check(
            rule=f"{f.detector_id}/{f.rule_id}",
            severity=f.severity,
            title=f.title,
            rows=tuple(sorted(f.rows)),
        )
        for f in checked.findings
    ]


# ----------------------------------------------------------------------------- the mechanism
#
# Two readers flag the bill: the app's checks and the model's passes. Their findings are sorted
# into one reading list in stages:
#   1. proven: check findings that prove an error from the bill's own values;
#   2. agreed: the other check findings and the model's suggestions on rows the other reader
#      flags too;
#   3. disputed: everything else, a claim for the judge (one more model request per part), kept
#      when the judge confirms it, then the ones it is unsure about; the rejected ones are left
#      out.
# A finding whose rows are all named by an earlier finding of the list adds nothing and is left
# out as well.

STAGES = ("proven", "agreed", "confirmed", "unsure")


@dataclass(slots=True)
class Judged:
    findings: list[Finding]  # the reading list
    stages: dict[str, int]  # findings of the list per stage
    claims: list[dict[str, Any]]  # every disputed claim with the judge's verdict
    parts: list[JudgedPart]  # the judge's requests
    stage_of: list[str] = field(default_factory=list)  # the stage of each finding of the list
    proven: frozenset[str] = frozenset()  # issue ids of the proven check findings


def _turns(first: Sequence[Finding], second: Sequence[Finding]) -> list[Finding]:
    return [f for pair in zip_longest(first, second) for f in pair if f is not None]


def _model_claim(suggestion: Suggestion) -> str:
    return " / ".join(
        f"{issue.issue_name or 'issue'}: {issue.why}" for issue in suggestion.issues[:3]
    )


def mechanism(
    bill: Bill,
    checked: Checked,
    proven: frozenset[str],
    suggestions: Sequence[Suggestion],
    judge: Any = None,
) -> Judged:
    """The reading list of the whole mechanism. ``judge`` takes the disputed claims and returns
    the judged parts (:func:`~app.agents.bill_review.judge_claims`); without one every disputed
    claim stays unsure."""
    model = model_findings(suggestions)
    by_row = {p.row_number: p.oz for p in bill.positions}
    sure = [f for f in checked.findings if f.issue_id in proven]
    soft = [f for f in checked.findings if f.issue_id not in proven]
    check_rows = {r for f in checked.findings for r in f.rows}
    model_rows = {r for f in model for r in f.rows}
    agreed = [f for f in soft if f.rows & model_rows]
    agreed += [f for f in model if f.rows & check_rows]
    disputed = [f for f in soft if not f.rows & model_rows]
    disputed += [f for f in model if not f.rows & check_rows]
    text = {f.issue_id: _model_claim(s) for f, s in zip(model, suggestions, strict=True)}
    claims: list[tuple[Claim, Finding]] = []
    for number, finding in enumerate(disputed, 1):
        oz = next((by_row[r] for r in sorted(finding.rows) if r in by_row), "")
        source = "model" if finding.detector_id == MODEL_DETECTOR else "checks"
        said = text[finding.issue_id] if source == "model" else finding.title
        claims.append((Claim(f"C{number}", oz, source, said), finding))
    parts: list[JudgedPart] = judge([c for c, _ in claims]) if judge is not None and claims else []
    verdicts: dict[str, Verdict] = {v.cid: v for part in parts for v in part.verdicts}

    def verdict(claim: Claim) -> str:
        return verdicts[claim.cid].verdict if claim.cid in verdicts else "unsure"

    staged: dict[str, list[Finding]] = {"proven": sure, "agreed": agreed}
    for name in ("confirmed", "unsure"):
        chosen = [(c, f) for c, f in claims if verdict(c) == name]
        staged[name] = _turns(
            [f for c, f in chosen if c.source == "checks"],
            [f for c, f in chosen if c.source == "model"],
        )
    listed: list[Finding] = []
    stage_of: list[str] = []
    named: set[int] = set()
    stages = dict.fromkeys(STAGES, 0)
    for name in STAGES:
        for finding in staged[name]:
            if finding.rows and finding.rows <= named:
                continue
            listed.append(finding)
            stage_of.append(name)
            named |= finding.rows
            stages[name] += 1
    return Judged(
        findings=listed,
        stage_of=stage_of,
        proven=proven,
        stages=stages,
        claims=[
            {
                "cid": c.cid,
                "source": c.source,
                "oz": c.oz,
                "rows": sorted(f.rows),
                "rule": f"{f.detector_id}/{f.rule_id}",
                "claim": c.text,
                "verdict": verdict(c),
                "judged": c.cid in verdicts,
                "why": verdicts[c.cid].why if c.cid in verdicts else "",
                "grounded": verdicts[c.cid].grounded if c.cid in verdicts else False,
            }
            for c, f in claims
        ],
        parts=parts,
    )


def mechanism_high(
    bill: Bill,
    checked: Checked,
    proven: frozenset[str],
    suggestions: Sequence[Suggestion],
    judge: Any = None,
) -> tuple[Judged, list[Suggestion]]:
    """The design measured with ``--judge-all``. Model claims of certainty high are candidates;
    the others go to a separate "worth a look" list (returned second, never judged or ranked).
    The judge rules on every check finding that is not proven (also those a model claim agrees
    with) and on every high-certainty claim. The reading list: proven; judge-confirmed check
    findings; agreed (a check finding and a model claim of any certainty on the same rows,
    whatever the judge said); judge-confirmed high-certainty claims. Every claim is kept with
    its verdict, rows, rule, certainty and passes, so other lists can be scored afterwards."""
    model = model_findings(suggestions)
    by_row = {p.row_number: p.oz for p in bill.positions}
    pairs = list(zip(model, suggestions, strict=True))
    high = [f for f, s in pairs if s.certainty == "high"]
    look = [s for _, s in pairs if s.certainty != "high"]
    model_rows = {r for f in model for r in f.rows}
    check_rows = {r for f in checked.findings for r in f.rows}
    sure = [f for f in checked.findings if f.issue_id in proven]
    soft = [f for f in checked.findings if f.issue_id not in proven]
    said = {f.issue_id: _model_claim(s) for f, s in pairs}
    suggestion_of = {f.issue_id: s for f, s in pairs}
    claims: list[tuple[Claim, Finding]] = []
    for number, finding in enumerate([*soft, *high], 1):
        oz = next((by_row[r] for r in sorted(finding.rows) if r in by_row), "")
        source = "model" if finding.detector_id == MODEL_DETECTOR else "checks"
        text = said[finding.issue_id] if source == "model" else finding.title
        claims.append((Claim(f"C{number}", oz, source, text), finding))
    parts: list[JudgedPart] = judge([c for c, _ in claims]) if judge is not None and claims else []
    verdicts: dict[str, Verdict] = {v.cid: v for part in parts for v in part.verdicts}

    def verdict(claim: Claim) -> str:
        return verdicts[claim.cid].verdict if claim.cid in verdicts else "unsure"

    ruled = {f.issue_id: verdict(c) for c, f in claims}
    staged = [
        ("proven", sure),
        ("confirmed", [f for f in soft if ruled[f.issue_id] == "confirmed"]),
        ("agreed", [f for f in soft if f.rows & model_rows]),
        ("confirmed", [f for f in high if ruled[f.issue_id] == "confirmed"]),
    ]
    listed: list[Finding] = []
    stage_of: list[str] = []
    named: set[int] = set()
    stages = dict.fromkeys(STAGES, 0)
    for name, findings in staged:
        for finding in findings:
            if finding.rows and finding.rows <= named:
                continue
            listed.append(finding)
            stage_of.append(name)
            named |= finding.rows
            stages[name] += 1
    records: list[dict[str, Any]] = []
    for c, f in claims:
        s = suggestion_of.get(f.issue_id)
        other = model_rows if c.source == "checks" else check_rows
        records.append(
            {
                "cid": c.cid,
                "issue_id": f.issue_id,
                "source": c.source,
                "oz": c.oz,
                "rows": sorted(f.rows),
                "rule": f"{f.detector_id}/{f.rule_id}",
                "certainty": s.certainty if s else None,
                "passes": sorted(set(s.passes)) if s else [],
                "agreed": bool(f.rows & other),
                "claim": c.text,
                "verdict": verdict(c),
                "judged": c.cid in verdicts,
                "why": verdicts[c.cid].why if c.cid in verdicts else "",
                "grounded": verdicts[c.cid].grounded if c.cid in verdicts else False,
            }
        )
    judged = Judged(
        findings=listed,
        stages=stages,
        claims=records,
        parts=parts,
        stage_of=stage_of,
        proven=proven,
    )
    return judged, look


def judge_rates(key: dict[str, Any] | None, judged: Judged) -> dict[str, dict[str, int]]:
    """Claims per source and verdict, and how many name a planted fault's row (none can on a
    clean bill)."""
    planted = {r for f in key["planted"] for r in f["rows"]} if key else set()
    rates: dict[str, dict[str, int]] = {}
    for claim in judged.claims:
        for label in (claim["source"], "all"):
            entry = rates.setdefault(f"{label}/{claim['verdict']}", {"claims": 0, "on_planted": 0})
            entry["claims"] += 1
            entry["on_planted"] += bool(planted & set(claim["rows"]))
    return dict(sorted(rates.items()))


# ----------------------------------------------------------------------------- scoring


def _rows(issue: Issue) -> set[int]:
    return set(issue.row_numbers)


def score(review: Review, key: dict[str, Any], control: Review | None = None) -> dict[str, Any]:
    """Match the kept issues of ``review`` with the answer key (rows of the faulty file)."""
    issues = review.issues
    clean_flagged = {i.oz for i in control.issues} if control is not None else set()
    keyed_rows: set[int] = set()
    planted: list[dict[str, Any]] = []
    for fault in key["planted"]:
        rows = set(fault["rows"])
        keyed_rows |= rows
        hits = [i for i in issues if _rows(i) & rows]
        first = next((i for i in hits if fault["row"] in i.row_numbers), hits[0] if hits else None)
        planted.append(
            {
                "id": fault["error_id"],
                "category": fault["finding_category"],
                "kind": fault["kind"],
                "oz": fault["oz"],
                "found": bool(hits),
                "localized": any(fault["row"] in i.row_numbers for i in hits),
                "grounded": any(i.grounded for i in hits),
                "category_match": any(i.category == fault["finding_category"] for i in hits),
                "flagged_in_clean": control is not None and fault["oz"] in clean_flagged,
                "issue": None if first is None else _brief(first),
            }
        )
    oddities = []
    for oddity in key["not_planted"]:
        rows = set(oddity["rows"])
        keyed_rows |= rows
        hits = [i for i in issues if _rows(i) & rows]
        oddities.append({"id": oddity["id"], "kind": oddity["kind"], "found": bool(hits)})
    trap_positions = {oz for trap in key["must_not_flag"] for oz in trap["positions"]}
    unmatched = [i for i in issues if not _rows(i) & keyed_rows]
    traps = [i for i in unmatched if i.oz in trap_positions]
    found = [p for p in planted if p["found"]]
    return {
        "planted_total": len(planted),
        "planted_found": len(found),
        "planted_localized": sum(p["localized"] for p in planted),
        "planted_found_grounded": sum(p["found"] and p["grounded"] for p in planted),
        "planted_found_specific": (
            sum(p["found"] and not p["flagged_in_clean"] for p in planted)
            if control is not None
            else None
        ),
        "planted_category_match": sum(p["category_match"] for p in planted),
        "found_by_category": dict(Counter(p["category"] for p in found)),
        "planted_by_category": dict(Counter(p["category"] for p in planted)),
        "oddities_total": len(oddities),
        "oddities_found": sum(o["found"] for o in oddities),
        "issues": len(issues),
        "issues_grounded": sum(i.grounded for i in issues),
        "issues_on_keyed_rows": len(issues) - len(unmatched),
        "issues_unmatched": len(unmatched),
        "issues_on_traps": len(traps),
        "planted": planted,
        "oddities": oddities,
        "unmatched": [_brief(i) for i in unmatched],
        "traps": [_brief(i) for i in traps],
    }


def _pass_score(
    review: Review, control: Review | None, key: dict[str, Any], name: str
) -> dict[str, Any]:
    """The score of one pass of a review in several passes."""

    def only(r: Review) -> Review:
        return Review(r.prompt_version, r.bill, [p for p in r.parts if p.focus == name], 0)

    s = score(only(review), key, None if control is None else only(control))
    return {
        "found": [p["id"] for p in s["planted"] if p["found"]],
        **{
            k: s[k]
            for k in (
                "planted_found",
                "planted_found_specific",
                "oddities_found",
                "issues",
                "issues_unmatched",
                "issues_on_traps",
            )
        },
    }


def _found_by(row_sets: Iterable[Iterable[int]], key: dict[str, Any]) -> dict[str, Any]:
    """The planted faults and real oddities of ``key`` whose rows meet one of ``row_sets``."""
    sets = [set(rows) for rows in row_sets]
    planted = [f["error_id"] for f in key["planted"] if any(r & set(f["rows"]) for r in sets)]
    oddities = [o["id"] for o in key["not_planted"] if any(r & set(o["rows"]) for r in sets)]
    return {
        "planted_found": len(planted),
        "found": planted,
        "oddities_found": len(oddities),
        "oddities": oddities,
    }


def together(
    review: Review,
    checks: Sequence[Check],
    suggestions: Sequence[Suggestion],
    key: dict[str, Any],
    top: int,
) -> dict[str, Any]:
    """The app's checks alone, the model alone, both, and what a Korrektor reads: the checks
    plus the first ``top`` suggestions."""
    model = [i.row_numbers for i in review.issues]
    found = [c.rows for c in checks]
    head = [s.row_numbers for s in suggestions[:top]]
    alone = _found_by(found, key)
    both = _found_by([*found, *model], key)
    return {
        "checks": {**alone, "findings": len(checks)},
        "model": _found_by(model, key),
        "together": {
            **both,
            "only_model": [f for f in both["found"] if f not in alone["found"]],
            "missed": [f["error_id"] for f in key["planted"] if f["error_id"] not in both["found"]],
        },
        "checks_and_top": {**_found_by([*found, *head], key), "items": len(checks) + len(head)},
    }


def ranked(suggestions: Sequence[Suggestion], key: dict[str, Any], top: int) -> dict[str, Any]:
    """The first ``top`` suggestions, each matched with the key."""
    traps = {oz for trap in key["must_not_flag"] for oz in trap["positions"]}
    listed = []
    for number, suggestion in enumerate(suggestions[:top], 1):
        rows = set(suggestion.row_numbers)
        planted = [f["error_id"] for f in key["planted"] if rows & set(f["rows"])]
        oddities = [o["id"] for o in key["not_planted"] if rows & set(o["rows"])]
        best = max(
            suggestion.issues,
            key=lambda i: (CERTAINTY.get(i.certainty or "", 1), i.grounded),
        )
        listed.append(
            {
                "rank": number,
                "oz": suggestion.oz,
                "score": suggestion.score,
                "passes": list(suggestion.passes),
                "certainty": suggestion.certainty,
                "grounded": suggestion.grounded,
                "checked": suggestion.checked,
                "planted": planted,
                "oddities": oddities,
                "trap": not planted and not oddities and suggestion.oz in traps,
                "type": f"{best.issue_type} {best.issue_name}" if best.issue_type else None,
                "why": best.why,
            }
        )
    return {
        "suggestions": len(suggestions),
        "on_unchecked_positions": sum(not s.checked for s in suggestions),
        "top": listed,
        "top_planted": sum(bool(r["planted"]) for r in listed),
        "top_oddities": sum(bool(r["oddities"]) and not r["planted"] for r in listed),
        "top_traps": sum(r["trap"] for r in listed),
    }


def _brief(issue: Issue) -> dict[str, Any]:
    return {
        "oz": issue.oz,
        "type": f"{issue.issue_type} {issue.issue_name}" if issue.issue_type else None,
        "category": issue.category,
        "certainty": issue.certainty,
        "grounded": issue.grounded,
        "quote": issue.quote,
        "why": issue.why,
    }


def run_stats(review: Review) -> dict[str, Any]:
    parts = review.parts
    reasons = Counter(r.reason.split(":")[0] for p in parts for r in p.rejected)
    return {
        "parts": len(parts),
        "parts_failed": sum(p.error is not None for p in parts),
        "parts_with_issues": sum(bool(p.issues) for p in parts),
        "seconds": round(sum(p.seconds for p in parts), 1),
        "prompt_chars_max": max((p.prompt_chars for p in parts), default=0),
        "prompt_tokens_max": max((p.prompt_tokens or 0 for p in parts), default=0),
        "prompt_tokens_total": sum(p.prompt_tokens or 0 for p in parts),
        "output_tokens_total": sum(p.output_tokens or 0 for p in parts),
        "rejected": sum(len(p.rejected) for p in parts),
        "rejected_by_reason": dict(reasons),
        "errors": [
            f"{p.focus + ' ' if p.focus else ''}part {p.part}: {p.error}" for p in parts if p.error
        ],
    }


# ----------------------------------------------------------------------------- report


def _yes(value: bool) -> str:
    return "yes" if value else "no"


def render(
    result: dict[str, Any], args: argparse.Namespace
) -> str:  # pragma: no cover - formatting only, checked by reading the report
    s = result["score"]
    stats = result["stats"]
    window = "the model's own" if args.provider == "openai" else f"{args.context_tokens} tokens"
    lines = [
        "# Sandwich review: results",
        "",
        f"Model `{result['model']}` ({args.provider}), prompt `{PROMPT_VERSION}`, context window "
        f"{window}, "
        + (
            "the whole bill as one part"
            if args.whole_bill
            else f"one part per section (at most {args.part_size} positions)"
        )
        + f", whole bill in the context: {_yes(not args.no_whole_bill)}, "
        + (f"passes: {args.passes}." if args.passes else f"issue types: {args.issue_types}."),
        f"Bill `{result['bill']}`; control `{result.get('control_bill') or 'none'}`. "
        f"The app's checks in the prompt: {_yes(not args.no_checks)}. Requests at the same "
        f"time per pass: {args.workers}. Wall time: "
        + ", ".join(f"{k} {v} s" for k, v in result["wall_seconds"].items())
        + ".",
        "",
    ]
    t = result["together"]
    r = result["ranked"]
    lines += [
        "## The app's checks and the model together",
        "",
        "| Who | Planted faults found | Real oddities found | Items to read |",
        "| --- | --- | --- | --- |",
        f"| The app's checks alone | {t['checks']['planted_found']} of {s['planted_total']} | "
        f"{t['checks']['oddities_found']} of {s['oddities_total']} | {t['checks']['findings']} |",
        f"| The model alone | {t['model']['planted_found']} | {t['model']['oddities_found']} | "
        f"{r['suggestions']} positions |",
        f"| Both | {t['together']['planted_found']} | {t['together']['oddities_found']} | |",
        f"| The checks and the top {args.top} suggestions | "
        f"{t['checks_and_top']['planted_found']} | {t['checks_and_top']['oddities_found']} | "
        f"{t['checks_and_top']['items']} |",
        "",
        f"Found only by the model: {', '.join(t['together']['only_model']) or 'none'}. "
        f"Missed by both: {', '.join(t['together']['missed']) or 'none'}.",
        "",
        f"## Top {args.top} suggestions of the model",
        "",
        f"The model flags {r['suggestions']} positions, {r['on_unchecked_positions']} of them "
        f"not flagged by the checks. In the top {args.top}: {r['top_planted']} on planted faults, "
        f"{r['top_oddities']} on real oddities, {r['top_traps']} on positions that must not be "
        "flagged.",
        "",
        "| # | OZ | Score | Passes | Certainty | Checks flag it too | In the key | Type | Why |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in r["top"]:
        match = ", ".join(row["planted"] + row["oddities"]) or ("trap" if row["trap"] else "-")
        lines.append(
            f"| {row['rank']} | {row['oz']} | {row['score']:g} | {', '.join(row['passes'])} | "
            f"{row['certainty'] or '-'} | {_yes(row['checked'])} | {match} | "
            f"{row['type'] or '-'} | {row['why'].replace('|', '/')} |"
        )
    lines += [
        "",
        "## Summary of the model's issues",
        "",
        "| Measure | Value |",
        "| --- | --- |",
        f"| Planted faults found | {s['planted_found']} of {s['planted_total']} |",
        f"| ... naming the fault's own row | {s['planted_localized']} |",
        f"| ... with a quote found in the bill | {s['planted_found_grounded']} |",
    ]
    if s["planted_found_specific"] is not None:
        lines.append(
            f"| ... and not flagged on the clean bill too | {s['planted_found_specific']} |"
        )
    lines += [
        f"| ... with the key's category | {s['planted_category_match']} |",
        f"| Real oddities of the original found | {s['oddities_found']} of {s['oddities_total']} |",
        f"| Issues reported (kept) | {s['issues']} ({s['issues_grounded']} grounded) |",
        f"| ... on rows the key lists | {s['issues_on_keyed_rows']} |",
        f"| ... not in the key (to judge) | {s['issues_unmatched']} |",
        f"| ... on positions that must not be flagged | {s['issues_on_traps']} |",
        f"| Answers rejected by the checks | {stats['rejected']} |",
        f"| Parts sent / failed | {stats['parts']} / {stats['parts_failed']} |",
        f"| Model time | {stats['seconds']} s |",
        f"| Largest prompt | {stats['prompt_chars_max']} characters, "
        f"{stats['prompt_tokens_max']} tokens |",
    ]
    control = result.get("control")
    if control is not None:
        lines += [
            f"| Issues on the clean bill (control) | {control['issues']} "
            f"({control['issues_grounded']} grounded) |",
            f"| ... positions flagged there, not flagged by the checks | "
            f"{control['suggestions_on_unchecked_positions']} |",
            f"| The checks' findings on the clean bill | {control['checks']} |",
        ]
    if result.get("by_pass"):
        lines += [
            "",
            "## By pass",
            "",
            "| Pass | Planted found | Not on clean bill too | Oddities | Issues | Not in key | "
            "Traps | Faults found |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for name, b in result["by_pass"].items():
            lines.append(
                f"| {name} | {b['planted_found']} | {b['planted_found_specific']} | "
                f"{b['oddities_found']} | {b['issues']} | {b['issues_unmatched']} | "
                f"{b['issues_on_traps']} | {', '.join(b['found'])} |"
            )
    lines += [
        "",
        "## Planted faults",
        "",
        "| Fault | Category | Kind | OZ | Found | Row | Clean bill flagged too | "
        "The model's issue |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for p in s["planted"]:
        issue = p["issue"]
        said = "" if issue is None else f"{issue['type'] or 'no type'}: {issue['why']}"
        lines.append(
            f"| {p['id']} | {p['category']} | {p['kind']} | {p['oz']} | {_yes(p['found'])} | "
            f"{_yes(p['localized'])} | {_yes(p['flagged_in_clean'])} | "
            f"{said.replace('|', '/')} |"
        )
    lines += ["", "## Issues not in the key (first 40)", ""]
    for issue in s["unmatched"][:40]:
        lines.append(
            f"- **{issue['oz']}** ({issue['type'] or 'no type'}, {issue['category']}, "
            f"grounded {_yes(issue['grounded'])}): {issue['why']}"
        )
    lines += ["", "## Rejected answers", ""]
    for reason, count in sorted(stats["rejected_by_reason"].items(), key=lambda kv: -kv[1]):
        lines.append(f"- {count} x {reason}")
    if stats["errors"]:
        lines += ["", "## Failed requests", "", *(f"- {e}" for e in stats["errors"])]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------- practice benchmark

PRACTICE_SEED = 20261121  # the seed of tools/practice_benchmark/run.py
# How the checks' findings and the model's ranked suggestions are put in one reading list.
ORDERS = ("checks", "model", "checks_then_model", "interleaved", "judged", "reading_list")
_ORDER_NAMES = {
    "checks": "The app's checks alone",
    "model": "The model alone (ranked)",
    "checks_then_model": "Checks, then the model",
    "interleaved": "Checks and model taking turns",
    "judged": "Proven, agreed, then judge-confirmed",
    "reading_list": "Default: proven, checks by rule hit rate, high-certainty claims",
}
DEFAULT_PASSES = "numbers,basis,text"


MODEL_DETECTOR = "model.sandwich"


def model_findings(suggestions: Sequence[Suggestion]) -> list[Finding]:
    """The ranked suggestions as findings of one check, for the shared scorer."""
    return [
        Finding(
            issue_id=f"model-{number}",
            detector_id=MODEL_DETECTOR,
            rule_id="suggestion",
            severity="medium",
            title=suggestion.issues[0].why[:200],
            rows=frozenset(suggestion.row_numbers),
            cells=frozenset(),
            score=suggestion.score,
        )
        for number, suggestion in enumerate(suggestions, 1)
    ]


def ordered(order: str, checks: Sequence[Finding], model: Sequence[Finding]) -> list[Finding]:
    if order == "checks":
        return list(checks)
    if order == "model":
        return list(model)
    if order == "checks_then_model":
        return [*checks, *model]
    return [f for pair in zip_longest(checks, model) for f in pair if f is not None]


def _by_difficulty(key: dict[str, Any], findings: Sequence[Finding]) -> dict[str, dict[str, int]]:
    tally: dict[str, dict[str, int]] = {}
    for fault in key["planted"]:
        rows = set(fault["rows"])
        ranks = [n for n, f in enumerate(findings, 1) if rows & f.rows]
        entry = tally.setdefault(
            str(fault.get("difficulty", "none")), {"planted": 0, "found": 0, "at20": 0, "at50": 0}
        )
        entry["planted"] += 1
        entry["found"] += bool(ranks)
        entry["at20"] += bool(ranks and ranks[0] <= 20)
        entry["at50"] += bool(ranks and ranks[0] <= 50)
    return dict(sorted(tally.items()))


def fault_trail(
    key: dict[str, Any],
    checks: Sequence[Finding],
    suggestions: Sequence[Suggestion],
    judged: Judged,
) -> list[dict[str, Any]]:
    """For every planted fault: which checks flag its rows (proven or soft), which of the model's
    suggestions do (passes, certainty), the judge's verdicts on the claims there, its first place
    in the judged list and its stage, and what became of it."""
    trail = []
    for fault in key["planted"]:
        rows = set(fault["rows"])
        ranks = [n for n, f in enumerate(judged.findings, 1) if rows & f.rows]
        by_checks = [
            {"rule": f"{f.detector_id}/{f.rule_id}", "proven": f.issue_id in judged.proven}
            for f in checks
            if rows & f.rows
        ]
        by_model = [
            {"oz": s.oz, "passes": list(s.passes), "certainty": s.certainty, "score": s.score}
            for s in suggestions
            if rows & set(s.row_numbers)
        ]
        verdicts = [
            {"claim": c["cid"], "source": c["source"], "verdict": c["verdict"]}
            for c in judged.claims
            if rows & set(c["rows"])
        ]
        place = ranks[0] if ranks else None
        if place is not None:
            fate = "first_50" if place <= 50 else "after_50"
        elif by_checks or by_model:
            fate = "lost_at_judge"
        else:
            fate = "never_flagged"
        trail.append(
            {
                "error_id": fault["error_id"],
                "kind": fault["kind"],
                "difficulty": fault.get("difficulty"),
                "rows": sorted(rows),
                "checks": by_checks,
                "model": by_model,
                "verdicts": verdicts,
                "place": place,
                "stage": judged.stage_of[place - 1] if place is not None else None,
                "fate": fate,
            }
        )
    return trail


FATES = ("first_50", "after_50", "lost_at_judge", "never_flagged")


def gap_trace(
    finished: dict[str, tuple[dict[str, Any], Checked, list[Suggestion], Judged]],
    clean: dict[str, Judged],
) -> dict[str, Any]:
    """The gap trace of the finished faulty bills (``finished``: bill -> key, checks, the
    model's suggestions, the judged list) and the judged lists of the clean bills."""
    faults: list[dict[str, Any]] = []
    first_50: dict[str, dict[str, dict[str, int]]] = {}
    must_not_flag: dict[str, dict[str, Any]] = {}
    verdicts: dict[str, dict[str, int]] = {}
    for bill, (key, checked, suggestions, judged) in finished.items():
        faults += [
            {"bill": bill, **f} for f in fault_trail(key, checked.findings, suggestions, judged)
        ]
        planted = {r for f in key["planted"] for r in f["rows"]}
        head = first_50.setdefault(bill, {})
        for finding, stage in list(zip(judged.findings, judged.stage_of, strict=True))[:50]:
            entry = head.setdefault(stage, {"listed": 0, "on_planted": 0})
            entry["listed"] += 1
            entry["on_planted"] += bool(finding.rows & planted)
        for control in key.get("must_not_flag", []):
            rows = set(control["rows"])
            stages = [
                stage
                for finding, stage in zip(judged.findings, judged.stage_of, strict=True)
                if finding.rows & rows
            ]
            if stages:
                must_not_flag[f"{bill}/{control['control_id']}"] = {
                    "rows": sorted(rows),
                    "hits": len(stages),
                    "stages": stages,
                }
        for claim in judged.claims:
            entry = verdicts.setdefault(
                f"{claim['source']}/{claim['verdict']}", {"claims": 0, "on_planted": 0}
            )
            entry["claims"] += 1
            entry["on_planted"] += bool(planted & set(claim["rows"]))
    by_kind: dict[str, dict[str, Any]] = {}
    for fault in faults:
        entry = by_kind.setdefault(
            fault["kind"],
            {"kind": fault["kind"], "difficulty": fault["difficulty"], "planted": 0}
            | dict.fromkeys(FATES, 0),
        )
        entry["planted"] += 1
        entry[fault["fate"]] += 1
    return {
        "bills": list(finished),
        "faults": faults,
        "by_kind": sorted(
            by_kind.values(), key=lambda e: (e["first_50"] - e["planted"], e["kind"])
        ),
        "first_50_by_stage": first_50,
        "judge_verdicts": dict(sorted(verdicts.items())),
        "clean_bills": {
            bill: {
                "listed": len(j.findings),
                "by_stage": j.stages,
                "verdicts": dict(Counter(c["verdict"] for c in j.claims)),
            }
            for bill, j in clean.items()
        },
        "must_not_flag_hits": must_not_flag,
    }


def render_gaps(trace: dict[str, Any]) -> str:  # pragma: no cover - formatting only
    lines = [
        "# Gap trace: what became of each planted fault",
        "",
        f"Bills: {', '.join(trace['bills'])}. Ids, kinds, rows and counts only.",
        "",
        "Fates: **first 50** (in the first 50 places of the judged list), **after 50** (in the "
        "list, further down), **lost at the judge** (a reader flagged its rows, but the judge "
        "rejected every claim there), **never flagged** (neither the checks nor the model name "
        "its rows).",
        "",
        "## By kind",
        "",
        "| Kind | Difficulty | Planted | First 50 | After 50 | Lost at the judge | Never flagged |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        *(
            f"| {k['kind']} | {k['difficulty']} | {k['planted']} | {k['first_50']} | "
            f"{k['after_50']} | {k['lost_at_judge']} | {k['never_flagged']} |"
            for k in trace["by_kind"]
        ),
    ]
    totals = {fate: sum(k[fate] for k in trace["by_kind"]) for fate in FATES}
    lines.append(
        f"| **all** | | {sum(k['planted'] for k in trace['by_kind'])} | {totals['first_50']} | "
        f"{totals['after_50']} | {totals['lost_at_judge']} | {totals['never_flagged']} |"
    )
    lines += [
        "",
        "## The first 50 places of each bill, by source",
        "",
        "Listed / on a planted fault's row (hit rate).",
        "",
        "| Bill | " + " | ".join(STAGES) + " |",
        "| --- | " + " | ".join("---:" for _ in STAGES) + " |",
    ]
    sums = {stage: [0, 0] for stage in STAGES}
    for bill, head in trace["first_50_by_stage"].items():
        cells = []
        for stage in STAGES:
            e = head.get(stage, {"listed": 0, "on_planted": 0})
            sums[stage][0] += e["listed"]
            sums[stage][1] += e["on_planted"]
            rate = f" ({e['on_planted'] / e['listed']:.0%})" if e["listed"] else ""
            cells.append(f"{e['listed']} / {e['on_planted']}{rate}")
        lines.append(f"| {bill} | " + " | ".join(cells) + " |")
    lines.append(
        "| **all** | "
        + " | ".join(f"{n} / {h}" + (f" ({h / n:.0%})" if n else "") for n, h in sums.values())
        + " |"
    )
    lines += [
        "",
        "## The judge's verdicts on the faulty bills",
        "",
        "| Claims from | Verdict | Claims | On a planted fault's row | Hit rate |",
        "| --- | --- | ---: | ---: | ---: |",
        *(
            f"| {label.split('/')[0]} | {label.split('/')[1]} | {e['claims']} | "
            f"{e['on_planted']} | {e['on_planted'] / e['claims']:.0%} |"
            for label, e in trace["judge_verdicts"].items()
            if e["claims"]
        ),
        "",
        "## Clean bills (nothing planted)",
        "",
        "| Bill | Listed | proven | agreed | confirmed | unsure | Claims rejected |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        *(
            f"| {bill} | {c['listed']} | "
            + " | ".join(str(c["by_stage"][stage]) for stage in STAGES)
            + f" | {c['verdicts'].get('rejected', 0)} |"
            for bill, c in trace["clean_bills"].items()
        ),
        "",
        "## Must-not-flag hits of the judged list, by control",
        "",
        "| Control | Rows | Hits | Stages |",
        "| --- | --- | ---: | --- |",
        *(
            f"| {control} | {', '.join(map(str, e['rows']))} | {e['hits']} | "
            f"{', '.join(e['stages'])} |"
            for control, e in trace["must_not_flag_hits"].items()
        ),
        "",
        "## Every planted fault",
        "",
        "| Bill | Fault | Kind | Difficulty | Rows | Checks (proven / soft) | Model (passes, "
        "certainty) | Judge | Place | Stage |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- |",
    ]
    for f in trace["faults"]:
        checks = ", ".join(
            f"{c['rule'].split('/')[-1]} ({'proven' if c['proven'] else 'soft'})"
            for c in f["checks"]
        )
        model = ", ".join(
            f"{'+'.join(m['passes'])} ({m['certainty'] or 'none'})" for m in f["model"]
        )
        judge = ", ".join(f"{v['source']}: {v['verdict']}" for v in f["verdicts"])
        lines.append(
            f"| {f['bill']} | {f['error_id']} | {f['kind']} | {f['difficulty']} | "
            f"{', '.join(map(str, f['rows']))} | {checks or '-'} | {model or '-'} | "
            f"{judge or '-'} | {f['place'] if f['place'] is not None else '-'} | "
            f"{f['stage'] or '-'} |"
        )
    return "\n".join(lines) + "\n"


class _OutOfCredit(Exception):
    """The hosted model refused for lack of credit: the run stops after the bill it was on."""


def _default_lists(
    args: argparse.Namespace,
    finished: dict[str, tuple[dict[str, Any], Checked, list[Suggestion], Judged]],
    clean_of: dict[str, Path],
    done: dict[Path, tuple[Review, Checked, list[Finding], Judged]],
    suggested: dict[Path, list[Suggestion]],
    variants: dict[str, Any],
    scored: Any,
    checks: dict[str, tuple[dict[str, Any], Checked, frozenset[str]]],
) -> None:
    """Score the default reading list (:mod:`app.evaluation.reading_list`) of every finished
    bill. Its rule rates are measured on the other base bills only (the variants that share a
    clean original are left out), never taken from the committed table, which has seen P1.
    They are counted on the checks of every faulty bill of the benchmark (``checks``), so a run
    that reviews only some bills (``--bills``) ranks the checks as a full run does."""
    by_bill = {
        stem: reading_list.count_rules(
            (f["rows"] for f in key["planted"]),
            (f for f in checked.findings if f.issue_id not in proven),
        )
        for stem, (key, checked, proven) in checks.items()
    }
    group = {stem: clean_of[stem].stem for stem in checks}
    look = args.out / "worth-a-look.jsonl"
    look.write_text("", encoding="utf-8")

    def made(path: Path, counts: reading_list.Counts) -> reading_list.ReadingList:
        _, checked, model, judged = done[path]
        return reading_list.reading_list(
            checked.findings, judged.proven, model, suggested[path], counts
        )

    for stem, (key, faulty, _, _) in finished.items():
        counts = reading_list.held_out_counts(by_bill, group, stem)
        mine = made(next(p for p in done if p.stem == stem), counts)
        theirs = made(clean_of[stem], counts)
        control = replace(done[clean_of[stem]][1], findings=theirs.findings)
        variants[stem]["orders"]["reading_list"] = scored(
            key, replace(faulty, findings=mine.findings), control
        )
        with look.open("a", encoding="utf-8") as stream:
            for f in mine.worth_a_look:
                entry = {"bill": stem, "rule": reading_list.rule_key(f), "rows": sorted(f.rows)}
                stream.write(json.dumps(entry) + "\n")


def practice(args: argparse.Namespace, reviewed: Any, wall: dict[str, float]) -> int:
    """Review every bill of the practice benchmark once (faulty and clean), then score the
    checks, the model and the two together in each order of :data:`ORDERS` with the shared
    answer-key scorer (F2 at 50, its clean-original discount and must-not-flag hits)."""
    every_key = sorted((args.practice / "out").glob("*-answer-key.json"))
    if not every_key:
        raise SystemExit(f"no *-answer-key.json in {args.practice / 'out'}")
    keys = [
        k
        for k in every_key
        if fnmatch.fnmatch(k.name.removesuffix("-answer-key.json"), args.bills or "*")
    ]
    if not keys:
        raise SystemExit(f"--bills {args.bills}: no faulty bill matches")
    done: dict[Path, tuple[Review, Checked, list[Finding], Judged]] = {}
    suggested: dict[Path, list[Suggestion]] = {}

    def get(path: Path) -> tuple[Review, Checked, list[Finding], Judged]:
        path = path.resolve()
        if path not in done:
            review, checked, suggestions, judged = reviewed(path, path.stem)
            done[path] = (review, checked, model_findings(suggestions), judged)
            suggested[path] = suggestions
        return done[path]

    def scored(key: dict[str, Any], shown: Checked, control: Checked) -> dict[str, Any]:
        s = answer_key.score(key, shown, control, seed=PRACTICE_SEED)
        return {
            "before": s["before_discount"],
            "after": s["after_discount"],
            "findings": s["findings"],
            "findings_on_clean_file": s["findings_on_clean_file"],
            "must_not_flag_hits": s["must_not_flag_hits"],
            "by_difficulty": _by_difficulty(key, shown.findings),
        }

    variants: dict[str, Any] = {}
    clean_of: dict[str, Path] = {}
    finished: dict[str, tuple[dict[str, Any], Checked, list[Suggestion], Judged]] = {}
    clean_lists: dict[str, Judged] = {}
    stopped: str | None = None
    progress = args.out / "bills.jsonl"
    progress.write_text("", encoding="utf-8")
    for key_path in keys:
        key = json.loads(key_path.read_text(encoding="utf-8"))
        bill = key_path.parent / str(key["file"])
        clean_path = key_path.parent / str(key["clean_file"])
        try:
            review, faulty, model, judged = get(bill)
            _, clean, clean_model, clean_judged = get(clean_path)
        except _OutOfCredit as error:
            stopped = str(error)
            break
        finished[bill.stem] = (key, faulty, suggested[bill.resolve()], judged)
        clean_lists[clean_path.stem] = clean_judged
        clean_of[bill.stem] = clean_path.resolve()
        orders: dict[str, Any] = {}
        for order in ORDERS:
            if order == "reading_list":
                continue  # needs every bill: below
            if order == "judged":
                shown = replace(faulty, findings=judged.findings)
                control = replace(clean, findings=clean_judged.findings)
            else:
                shown = replace(faulty, findings=ordered(order, faulty.findings, model))
                control = replace(clean, findings=ordered(order, clean.findings, clean_model))
            orders[order] = scored(key, shown, control)
        variants[bill.stem] = {
            "planted": len(key["planted"]),
            "matches_key": hashlib.sha256(bill.read_bytes()).hexdigest() == key.get("file_sha256"),
            "orders": orders,
            "stats": run_stats(review),
            "judge": {"stages": judged.stages, "rates": judge_rates(key, judged)},
        }
        line = {
            "bill": bill.stem,
            "f2_at_50": {o: orders[o]["before"]["f2_at_50"] for o in orders},
            "found": {o: orders[o]["before"]["found"] for o in orders},
            "stages": judged.stages,
        }
        with progress.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(line) + "\n")
        print(
            f"[{bill.stem} done] F2@50 checks {line['f2_at_50']['checks']:.4f}, judged "
            f"{line['f2_at_50']['judged']:.4f}",
            flush=True,
        )
    if not variants:
        print(f"stopped before a bill was finished: {stopped}")
        return 1
    checks: dict[str, tuple[dict[str, Any], Checked, frozenset[str]]] = {}
    for key_path in every_key:  # the checks of every faulty bill, for the held-out rule rates
        key = json.loads(key_path.read_text(encoding="utf-8"))
        bill = (key_path.parent / str(key["file"])).resolve()
        clean_of.setdefault(bill.stem, (key_path.parent / str(key["clean_file"])).resolve())
        if bill in done:
            checks[bill.stem] = (key, done[bill][1], done[bill][3].proven)
        else:
            _, checked, proven = load_checked(bill)
            checks[bill.stem] = (key, checked, proven)
    _default_lists(args, finished, clean_of, done, suggested, variants, scored, checks)
    ablation = review_ablation.ablate(
        {stem: key for stem, (key, _, _) in checks.items()},
        {stem: (checked, proven) for stem, (_, checked, proven) in checks.items()},
        {
            path.stem: review_ablation.Bill(checked, judged.proven, review, suggested[path])
            for path, (review, checked, _, judged) in done.items()
        },
        {stem: path.stem for stem, path in clean_of.items()},
        seed=PRACTICE_SEED,
    )
    (args.out / review_ablation.FILE).write_text(json.dumps(ablation, indent=1), encoding="utf-8")
    (args.out / "ablation.md").write_text(review_ablation.render(ablation), encoding="utf-8")
    totals: dict[str, Any] = {}
    for order in ORDERS:
        runs_ = [v["orders"][order] for v in variants.values()]
        difficulty: dict[str, dict[str, int]] = {}
        for r in runs_:
            for label, tally in r["by_difficulty"].items():
                merged = difficulty.setdefault(label, dict.fromkeys(tally, 0))
                for name, value in tally.items():
                    merged[name] += value
        totals[order] = {
            "f2_at_50": statistics.mean(r["before"]["f2_at_50"] or 0.0 for r in runs_),
            "discounted_f2_at_50": statistics.mean(r["after"]["f2_at_50"] or 0.0 for r in runs_),
            **{
                name: sum(r["before"][field] for r in runs_)
                for name, field in (
                    ("found", "found"),
                    ("at20", "found_in_first_20"),
                    ("at50", "found_in_first_50"),
                )
            },
            "discounted_found": sum(r["after"]["found"] for r in runs_),
            "findings": sum(r["findings"] for r in runs_),
            "must_not_flag_hits": sum(r["must_not_flag_hits"] for r in runs_),
            "by_difficulty": dict(sorted(difficulty.items())),
        }
    every = [r for r, _, _, _ in done.values()]
    asked = [part for _, _, _, j in done.values() for part in j.parts]

    def combine(rates: Iterable[dict[str, dict[str, int]]]) -> dict[str, dict[str, int]]:
        total: dict[str, dict[str, int]] = {}
        for one in rates:
            for label, entry in one.items():
                into = total.setdefault(label, dict.fromkeys(entry, 0))
                for name, value in entry.items():
                    into[name] += value
        return dict(sorted(total.items()))

    result = {
        "prompt_version": PROMPT_VERSION,
        "judge_version": JUDGE_VERSION,
        "provider": args.provider,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "whole_bill": args.whole_bill,
        "settings": {
            "part_size": None if args.whole_bill else args.part_size,
            "passes": args.passes,
            "no_checks": args.no_checks,
            "whole_bill_context": not args.no_whole_bill,
            "bills": args.bills or "*",
        },
        "replayed_from": str(args.replay) if args.replay else None,
        "planted": sum(v["planted"] for v in variants.values()),
        "wall_seconds": wall,
        "prompt_tokens_total": sum(run_stats(r)["prompt_tokens_total"] for r in every),
        "output_tokens_total": sum(run_stats(r)["output_tokens_total"] for r in every),
        "parts_failed": sum(run_stats(r)["parts_failed"] for r in every),
        "judge": {
            "requests": len(asked),
            "failed": sum(p.error is not None for p in asked),
            "prompt_tokens_total": sum(p.prompt_tokens or 0 for p in asked),
            "output_tokens_total": sum(p.output_tokens or 0 for p in asked),
            "faulty": combine(v["judge"]["rates"] for v in variants.values()),
            "clean": combine(
                judge_rates(None, j) for path, (_, _, _, j) in done.items() if "-clean" in path.stem
            ),
            "stages": {
                name: sum(v["judge"]["stages"][name] for v in variants.values()) for name in STAGES
            },
        },
        "stopped": stopped,
        "bills_finished": list(variants),
        "judge_model": args.judge_model or args.model,
        "usage_by_model": [m.usage() for m in getattr(reviewed, "meters", [])],
        "totals": totals,
        "variants": variants,
        "clean_findings": {
            path.stem: {
                "checks": len(checked.findings),
                "model": len(model),
                "judged": len(judged.findings),
            }
            for path, (_, checked, model, judged) in done.items()
            if path.stem.endswith("-clean")
        },
    }
    (args.out / "practice.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    (args.out / "practice.md").write_text(render_practice(result), encoding="utf-8")
    trace = gap_trace(finished, clean_lists)
    (args.out / "gaps.json").write_text(json.dumps(trace, indent=1), encoding="utf-8")
    (args.out / "gaps.md").write_text(render_gaps(trace), encoding="utf-8")
    if stopped:
        print(f"stopped for lack of credit ({stopped}); finished: {', '.join(variants)}")
    print(
        f"F2@50 checks {totals['checks']['f2_at_50']:.4f}, model {totals['model']['f2_at_50']:.4f}"
        f", checks then model {totals['checks_then_model']['f2_at_50']:.4f}, judged "
        f"{totals['judged']['f2_at_50']:.4f}; found {totals['checks']['found']} by the checks, "
        f"{totals['checks_then_model']['found']} by both, {totals['judged']['found']} in the "
        f"judged list, of {result['planted']}; report: {args.out / 'practice.md'}"
    )
    return 1 if stopped else 0


def render_practice(result: dict[str, Any]) -> str:  # pragma: no cover - formatting only
    totals = result["totals"]
    planted = result["planted"]
    lines = [
        "# Practice benchmark P1: the app's checks and the sandwich review",
        "",
        f"Model `{result['model']}` ({result['provider']}, reasoning "
        f"{result['reasoning_effort'] or 'default'}), prompt `{result['prompt_version']}`, "
        + (
            "the whole bill as one part per pass. "
            if result.get("whole_bill")
            else "one part per section. "
        )
        + f"{planted} planted faults in {len(result['variants'])} faulty bills. Tokens of the "
        f"passes: {result['prompt_tokens_total']} in, {result['output_tokens_total']} out; "
        f"failed requests: {result['parts_failed']}"
        + (
            f" (answers replayed from `{result['replayed_from']}`)"
            if result["replayed_from"]
            else ""
        )
        + f". Judge (`{result['judge_version']}`): {result['judge']['requests']} requests, "
        f"{result['judge']['prompt_tokens_total']} tokens in, "
        f"{result['judge']['output_tokens_total']} out, {result['judge']['failed']} failed. "
        f"Wall time: {sum(result['wall_seconds'].values()):.0f} s for all bills."
        + "".join(
            f" {u['model']}: {u.get('requests', 0)} requests, {u.get('input', 0)} tokens in "
            f"(+{u.get('cache_read', 0)} read from the cache, {u.get('cache_write', 0)} written "
            f"to it), {u.get('output', 0)} out"
            + (f", about {u['cost_usd']:.2f} USD." if u.get("cost_usd") is not None else ".")
            for u in result["usage_by_model"]
        )
        + (
            f" **Stopped for lack of credit** ({result['stopped']}); bills finished: "
            f"{', '.join(result['bills_finished'])}."
            if result["stopped"]
            else ""
        ),
        "",
        "F2 at 50 is the mean over the faulty bills, as in `tools/practice_benchmark/run.py`. "
        "Found counts a fault when any finding of the list names one of its rows.",
        "",
        "| Reading list | F2@50 | F2@50 after clean discount | Found | First 20 | First 50 | "
        "Findings | Must-not-flag hits |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for order in ORDERS:
        t = totals[order]
        lines.append(
            f"| {_ORDER_NAMES[order]} | {t['f2_at_50']:.4f} | {t['discounted_f2_at_50']:.4f} | "
            f"{t['found']}/{planted} | {t['at20']} | {t['at50']} | {t['findings']} | "
            f"{t['must_not_flag_hits']} |"
        )
    lines += [
        "",
        "## By difficulty (found anywhere / in the first 50)",
        "",
        "| Reading list | " + " | ".join(totals["checks"]["by_difficulty"]) + " |",
        "| --- | " + " | ".join("---" for _ in totals["checks"]["by_difficulty"]) + " |",
    ]
    for order in ORDERS:
        cells = [
            f"{d['found']} / {d['at50']} of {d['planted']}"
            for d in totals[order]["by_difficulty"].values()
        ]
        lines.append(f"| {_ORDER_NAMES[order]} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## By bill (F2@50)",
        "",
        "| Bill | " + " | ".join(_ORDER_NAMES[o] for o in ORDERS) + " | Found by checks / both |",
        "| --- | " + " | ".join("---:" for _ in ORDERS) + " | ---: |",
    ]
    for name, variant in result["variants"].items():
        o = variant["orders"]
        lines.append(
            f"| {name} | "
            + " | ".join(f"{(o[x]['before']['f2_at_50'] or 0):.4f}" for x in ORDERS)
            + f" | {o['checks']['before']['found']} / {o['checks_then_model']['before']['found']}"
            f" of {variant['planted']} |"
        )
    judge = result["judge"]
    lines += [
        "",
        "## The judge: disputed claims by verdict",
        "",
        "A claim is disputed when only one reader flags its rows: a check that does not prove an "
        "error, or a model suggestion no check backs. On a planted fault: the claim names one of "
        "a planted fault's rows.",
        "",
        "| Claims | Verdict | Faulty bills | On a planted fault | Hit rate | Clean bills |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for source in ("checks", "model", "all"):
        for verdict in VERDICTS:
            f = judge["faulty"].get(f"{source}/{verdict}", {"claims": 0, "on_planted": 0})
            c = judge["clean"].get(f"{source}/{verdict}", {"claims": 0})
            rate = f"{f['on_planted'] / f['claims']:.0%}" if f["claims"] else "-"
            lines.append(
                f"| {source} | {verdict} | {f['claims']} | {f['on_planted']} | {rate} | "
                f"{c['claims']} |"
            )
    lines += [
        "",
        "Findings of the judged list on the faulty bills, by stage: "
        + ", ".join(f"{name} {count}" for name, count in judge["stages"].items())
        + " (rejected claims and findings on rows already listed are left out).",
    ]
    lines += [
        "",
        "The gap trace (every planted fault, by kind) is in `gaps.md`.",
    ]
    lines += [
        "",
        "## Findings on the clean originals",
        "",
        "| Bill | Checks | Model (positions) | Judged list |",
        "| --- | ---: | ---: | ---: |",
        *(
            f"| {name} | {c['checks']} | {c['model']} | {c['judged']} |"
            for name, c in result["clean_findings"].items()
        ),
        "",
        "Row overlap does not prove the finding names the fault's reason. The model's "
        "suggestions are suspicions for the Korrektor, never confirmed errors.",
    ]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------- command line


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.evaluation.llm_review")
    parser.add_argument("--bill", type=Path, help="the bill to review")
    parser.add_argument("--answer-key", type=Path)
    parser.add_argument(
        "--practice",
        type=Path,
        help="instead of --bill: the practice benchmark folder (Practice Benchmark P1); every "
        "faulty bill of its out/ and its clean original, scored with the shared scorer",
    )
    parser.add_argument("--clean", type=Path, help="the clean bill, reviewed as the control")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--provider",
        choices=("ollama", "openai", "anthropic"),
        default="ollama",
        help="ollama: the local server; openai: a model behind the OpenAI API; anthropic: Claude "
        "through Anthropic's SDK (the optional llm extra). Hosted: the bill leaves the machine",
    )
    parser.add_argument("--model", help="default: qwen2.5:7b-instruct for ollama")
    parser.add_argument("--base-url", help="default: the local Ollama server or api.openai.com")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY", help="openai: key variable")
    parser.add_argument(
        "--reasoning-effort",
        help="openai: e.g. none, low, medium; anthropic: the effort, low to max (default medium)",
    )
    parser.add_argument(
        "--judge-model",
        help="anthropic: the model of the judge (default: --model), e.g. claude-opus-5-5",
    )
    parser.add_argument("--temperature", type=float, help="openai: left to the model if unset")
    parser.add_argument("--context-tokens", type=int, default=32768)
    parser.add_argument("--max-output-tokens", type=int, default=1024)
    parser.add_argument("--timeout", type=float, default=1800.0, help="seconds per request")
    parser.add_argument(
        "--part-size", type=int, default=40, help="a section with more positions is split"
    )
    parser.add_argument(
        "--issue-types",
        help="one question about these issue numbers instead of the passes, e.g. 081,080,018, "
        "or 'all' for the 135",
    )
    parser.add_argument(
        "--passes",
        help=f"focused passes (default {DEFAULT_PASSES}): 'all' or names from "
        + ", ".join(PASSES)
        + "; the bill is asked once per pass and the issues are scored together",
    )
    parser.add_argument("--parts", help="only these parts, e.g. 1,5,9")
    parser.add_argument(
        "--bills",
        help="--practice: review only the faulty bills whose name matches this pattern (e.g. "
        "'bill-A-*') and their clean originals; the checks' hit rates still come from every bill",
    )
    parser.add_argument(
        "--whole-bill",
        action="store_true",
        default=True,
        help="the default: the whole bill as one part per pass; a bill too long for the "
        "model's context fails on its own request (it is never cut)",
    )
    parser.add_argument(
        "--split-by-section",
        dest="whole_bill",
        action="store_false",
        help="one part per section (at most --part-size positions) instead of the whole bill",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="openai: requests of every pass sent at the same time, all passes at once",
    )
    parser.add_argument("--top", type=int, default=20, help="length of the ranked list scored")
    parser.add_argument(
        "--no-checks", action="store_true", help="leave the app's check findings out of the prompt"
    )
    parser.add_argument(
        "--no-whole-bill", action="store_true", help="leave the position index out of the context"
    )
    parser.add_argument(
        "--num-gpu", type=int, help="model layers on the GPU (0: CPU only; default: the server's)"
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="--practice: also ask the judge about the disputed claims (off by default; the "
        "default list does not use it)",
    )
    parser.add_argument(
        "--judge-all",
        action="store_true",
        help="--practice: the high-certainty design (mechanism_high): only certainty-high model "
        "claims are ranked, the others go to judge-all-worth-a-look.jsonl; the judge rules on "
        "every "
        "unproven check finding and every high-certainty claim (claims.jsonl)",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="--practice: leave the disputed claims unjudged (all unsure) instead of asking the "
        "model once more per part",
    )
    parser.add_argument(
        "--replay",
        type=Path,
        help="an earlier OUT_DIR: take the passes' answers from its parts.jsonl and the judge's "
        "from its judge.jsonl (same prompt) instead of asking the model again",
    )
    parser.add_argument("--dry-run", action="store_true", help="build the prompts, call no model")
    return parser


DOTENV = Path(__file__).resolve().parents[2] / ".env"  # backend/.env, ignored by git


def load_dotenv(path: Path = DOTENV) -> list[str]:
    """Read ``KEY=VALUE`` lines of a local ``.env`` file into ``os.environ`` for keys that are
    not set already (a variable of the shell or the user wins). Blank lines and ``#`` comments
    are skipped, ``export`` and quotes around the value are allowed. Returns the names it set,
    never the values; a missing file sets nothing."""
    if not path.is_file():
        return []
    loaded: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.removeprefix("export ").partition("=")
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name and value and not os.environ.get(name, "").strip():
            os.environ[name] = value
            loaded.append(name)
    return loaded


def _generator_factory(args: argparse.Namespace) -> Any:
    """Check the model settings before any work and return a function that makes the
    generator (not called on a dry run); with ``anthropic`` it takes the model to use."""
    if args.provider == "anthropic":
        if not args.model:
            raise SystemExit("--provider anthropic needs --model, for example claude-haiku-5-5")
        if not os.environ.get("ANTHROPIC_API_KEY", "").strip() and not args.dry_run:
            raise SystemExit(
                "--provider anthropic: ANTHROPIC_API_KEY is not set (as an environment variable "
                "or in backend/.env, see backend/.env.example)"
            )
        effort = args.reasoning_effort or "medium"
        return lambda model=None: ClaudeGenerator(
            model=model or args.model,
            max_output_tokens=args.max_output_tokens,
            timeout=args.timeout,
            effort=effort,
        )
    if args.judge_model:
        raise SystemExit("--judge-model needs --provider anthropic")
    if args.provider == "openai":
        if not args.model:
            raise SystemExit("--provider openai needs --model, for example gpt-6-luna")
        api_key = os.environ.get(args.api_key_env, "").strip()
        if not api_key and not args.dry_run:
            raise SystemExit(
                f"--provider openai: the environment variable {args.api_key_env} is not set"
            )
        base_url = args.base_url or "https://api.openai.com/v1"
        return lambda model=None: _OpenAIGenerator(
            base_url=base_url,
            model=args.model,
            api_key=api_key,
            max_output_tokens=args.max_output_tokens,
            timeout=args.timeout,
            reasoning_effort=args.reasoning_effort,
            temperature=args.temperature,
        )
    if args.workers > 1:
        raise SystemExit("--workers above 1 needs a hosted provider (openai or anthropic)")
    args.model = args.model or "qwen2.5:7b-instruct"
    settings = LLMSettings(
        provider="ollama",
        base_url=args.base_url or "http://127.0.0.1:11434",
        model=args.model,
        context_tokens=args.context_tokens,
        max_output_tokens=args.max_output_tokens,
        request_timeout_seconds=args.timeout,
    )
    check_configured_model(settings)
    return lambda model=None: _Generator(settings, args.num_gpu)


def _passes(args: argparse.Namespace) -> dict[str, dict[str, tuple[str, str]]]:
    if args.passes is None and args.issue_types is None:
        args.passes = DEFAULT_PASSES
    if args.passes:
        names = list(PASSES) if args.passes == "all" else args.passes.split(",")
        unknown = [n for n in names if n not in PASSES]
        if unknown:
            raise SystemExit(f"unknown passes: {', '.join(unknown)}")
        return {n: load_issue_types(PASSES[n]) for n in names}
    chosen = None if args.issue_types == "all" else args.issue_types.split(",")
    return {"": load_issue_types(chosen)}


Reviewed = tuple[Review, Checked, list[Suggestion], Judged]


def _saved_parts(path: Path) -> dict[str, list[PartResult]]:
    """The answered parts of an earlier run (its ``parts.jsonl``), by bill."""
    saved: dict[str, list[PartResult]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        label = data.pop("bill")
        issues = [
            Issue(
                **{
                    **i,
                    "row_numbers": tuple(i["row_numbers"]),
                    "related_oz": tuple(i["related_oz"]),
                }
            )
            for i in data.pop("issues")
        ]
        rejected = [Rejected(**r) for r in data.pop("rejected")]
        part = PartResult(**data)
        part.issues, part.rejected = issues, rejected
        saved.setdefault(label, []).append(part)
    return saved


def _saved_verdicts(path: Path) -> dict[str, str]:
    """Prompt hash -> the judge's answer, from an earlier run's ``judge.jsonl``."""
    if not path.exists():
        return {}
    saved: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            data = json.loads(line)
            if data.get("error") is None and data.get("prompt_sha"):
                saved[data["prompt_sha"]] = data["raw"]
    return saved


class _Remembered:
    """A generator that answers a prompt it has an earlier answer for from that answer (no
    tokens), and asks ``ask`` otherwise. Remembers the hash of each thread's last prompt."""

    def __init__(self, ask: Any, saved: dict[str, str]) -> None:
        self._ask = ask
        self._saved = saved
        self._local = threading.local()

    @property
    def last_usage(self) -> tuple[int | None, int | None]:
        usage: tuple[int | None, int | None] = getattr(self._local, "usage", (None, None))
        return usage

    @property
    def last_sha(self) -> str:
        return str(getattr(self._local, "sha", ""))

    def __call__(self, prompt: str) -> str:
        sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        self._local.sha = sha
        if sha in self._saved:
            self._local.usage = (0, 0)
            return self._saved[sha]
        self._local.usage = (None, None)
        answer = str(self._ask(prompt))
        self._local.usage = getattr(self._ask, "last_usage", (None, None))
        return answer


def _stop_if_out_of_credit(label: str, parts: Iterable[Any]) -> None:
    for part in parts:
        if part.error and any(code in part.error for code in STOP_CODES):
            raise _OutOfCredit(f"{label}: {part.error}")


def _reviewer(
    args: argparse.Namespace,
    passes: dict[str, dict[str, tuple[str, str]]],
    make_generator: Any,
) -> tuple[Any, dict[str, float]]:
    """A function that reads, checks and reviews one bill (every pass, or the answers of
    ``--replay``), then (``--practice``) judges the disputed claims, and the wall time of each
    bill it reviewed."""
    only = [int(p) for p in args.parts.split(",")] if args.parts else None
    whole = not args.no_whole_bill
    answered = args.out / "parts.jsonl"
    answered.write_text("", encoding="utf-8")
    verdicts_file = args.out / "judge.jsonl"
    replayed = _saved_parts(args.replay / "parts.jsonl") if args.replay else None
    remembered = _saved_verdicts(args.replay / "judge.jsonl") if args.replay else {}
    verdicts_file.write_text("", encoding="utf-8")
    if args.judge_all:
        for name in ("claims.jsonl", "judge-all-worth-a-look.jsonl"):
            (args.out / name).write_text("", encoding="utf-8")
    written = threading.Lock()
    wall: dict[str, float] = {}
    judging = args.practice is not None and (args.judge or args.judge_all) and not args.no_judge
    generator = None if args.dry_run else make_generator()
    judge_generator = generator
    if generator is not None and args.judge_model and args.judge_model != args.model:
        judge_generator = make_generator(args.judge_model)

    def reviewed(path: Path, label: str) -> Reviewed:
        bill, checked, proven = load_checked(path)
        facts = facts_from(bill, ((f.rows, f.title) for f in checked.findings))
        first = partition(bill, args.part_size, whole=args.whole_bill)[0]
        prompts = args.out / "prompts"
        prompts.mkdir(exist_ok=True)
        given = None if args.no_checks else facts

        def progress(part: Any) -> None:
            with written, answered.open("a", encoding="utf-8") as stream:
                line = {"bill": label, **asdict(part)}
                stream.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
                print(
                    f"{label} {part.focus + ' ' if part.focus else ''}part {part.part} "
                    f"({part.section}): {len(part.issues)} issues, "
                    f"{len(part.rejected)} rejected, {part.seconds} s"
                    + (f", {part.error}" if part.error else ""),
                    flush=True,
                )

        def one_pass(name: str) -> Review:
            types = passes[name]
            context = context_layer(bill, types, whole_bill=whole)
            (prompts / f"{label}-{name + '-' if name else ''}part-1.txt").write_text(
                build_prompt(bill, first, context, issue_types=types, facts=given),
                encoding="utf-8",
            )
            return review_bill(
                bill,
                generator if generator is not None else (lambda _prompt: EMPTY_ANSWER),
                part_size=args.part_size,
                issue_types=types,
                only_parts=only,
                whole_bill=whole,
                facts=given,
                workers=args.workers,
                usage=None if generator is None else (lambda: generator.last_usage),
                on_part=None if generator is None else progress,
                focus=name,
                one_part=args.whole_bill,
            )

        start = time.monotonic()
        if replayed is not None:
            if label not in replayed:
                raise SystemExit(f"--replay: no saved answers for {label}")
            saved = [p for p in replayed[label] if p.focus in passes or not p.focus]
            for part in saved:
                progress(part)
            reviews = [Review("replayed", bill.name, saved, 0)]
        elif args.workers > 1 and len(passes) > 1:
            with ThreadPoolExecutor(max_workers=len(passes)) as pool:
                reviews = list(pool.map(one_pass, passes))
        else:
            reviews = [one_pass(name) for name in passes]
        review = Review(
            reviews[0].prompt_version,
            reviews[0].bill,
            [part for r in reviews for part in r.parts],
            max(r.context_chars for r in reviews),
        )
        _stop_if_out_of_credit(label, review.parts)
        suggestions = rank(review, facts)
        judge = None
        if judging:
            ask = _Remembered(
                judge_generator
                if judge_generator is not None
                else (lambda _prompt: EMPTY_VERDICTS),
                remembered,
            )

            def judged_progress(part: JudgedPart) -> None:
                with written, verdicts_file.open("a", encoding="utf-8") as stream:
                    line = {"bill": label, "prompt_sha": ask.last_sha, **asdict(part)}
                    stream.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
                    tally = Counter(v.verdict for v in part.verdicts)
                    print(
                        f"{label} judge part {part.part} ({part.section}): "
                        + ", ".join(f"{tally[v]} {v}" for v in VERDICTS)
                        + f", {part.seconds} s"
                        + (f", {part.error}" if part.error else ""),
                        flush=True,
                    )

            def judge(claims: list[Claim]) -> list[JudgedPart]:
                return judge_claims(
                    bill,
                    claims,
                    ask,
                    part_size=args.part_size,
                    workers=args.workers,
                    usage=lambda: ask.last_usage,
                    on_part=judged_progress,
                    whole=args.whole_bill,
                )

        if args.judge_all:
            judged, look = mechanism_high(bill, checked, proven, suggestions, judge)
            with written:
                with (args.out / "claims.jsonl").open("a", encoding="utf-8") as stream:
                    for record in judged.claims:
                        line = {"bill": label, **record}
                        stream.write(json.dumps(line, ensure_ascii=False) + "\n")
                with (args.out / "judge-all-worth-a-look.jsonl").open(
                    "a", encoding="utf-8"
                ) as stream:
                    for s in look:
                        entry = {
                            "bill": label,
                            "oz": s.oz,
                            "rows": list(s.row_numbers),
                            "certainty": s.certainty,
                            "passes": sorted(set(s.passes)),
                            "issue_types": [i.issue_type for i in s.issues],
                        }
                        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        else:
            judged = mechanism(bill, checked, proven, suggestions, judge)
        _stop_if_out_of_credit(label, judged.parts)
        wall[label] = round(time.monotonic() - start, 1)
        return review, checked, suggestions, judged

    # what the hosted models report about their tokens and cost, read by practice()
    reviewed.meters = [  # type: ignore[attr-defined]  # a function attribute, set once
        g for g in dict.fromkeys((generator, judge_generator)) if hasattr(g, "usage")
    ]
    return reviewed, wall


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    load_dotenv()
    if args.practice is None and (args.bill is None or args.answer_key is None):
        raise SystemExit("give --bill and --answer-key, or --practice FOLDER")
    make_generator = _generator_factory(args)
    passes = _passes(args)
    args.out.mkdir(parents=True, exist_ok=True)
    reviewed, wall = _reviewer(args, passes, make_generator)
    if args.practice is not None:
        return practice(args, reviewed, wall)
    key = json.loads(args.answer_key.read_text(encoding="utf-8"))
    review, checked, suggestions, judged = reviewed(args.bill, "bill")
    checks = checks_of(checked)
    # the default reading list, with the rates of the committed table (measured on P1: a P1
    # bill scored here has been seen by it; --practice scores held out)
    default = reading_list.reading_list(
        checked.findings,
        judged.proven,
        model_findings(suggestions),
        suggestions,
        reading_list.load_counts(),
    )
    control = None
    if args.clean is not None:
        clean, clean_checked, clean_suggestions, _ = reviewed(args.clean, "clean")
        control = (clean, checks_of(clean_checked), clean_suggestions)
    result: dict[str, Any] = {
        "prompt_version": PROMPT_VERSION,
        "provider": args.provider,
        "model": args.model,
        "issue_types": {name or "single": list(types) for name, types in passes.items()},
        "bill": args.bill.name,
        "control_bill": args.clean.name if args.clean else None,
        "checks_in_prompt": not args.no_checks,
        "wall_seconds": wall,
        "score": score(review, key, None if control is None else control[0]),
        "together": together(review, checks, suggestions, key, args.top),
        "ranked": ranked(suggestions, key, args.top),
        "reading_list": [
            {"rule": reading_list.rule_key(f), "rows": sorted(f.rows), "stage": stage}
            for f, stage in zip(default.findings, default.stage_of, strict=True)
        ],
        "worth_a_look": [
            {"rule": reading_list.rule_key(f), "rows": sorted(f.rows)} for f in default.worth_a_look
        ],
        "stats": run_stats(review),
        "checks": [asdict(c) for c in checks],
        "parts": [asdict(p) for p in review.parts],
    }
    if args.passes:
        result["by_pass"] = {
            name: _pass_score(review, None if control is None else control[0], key, name)
            for name in passes
        }
    if control is not None:
        clean, clean_checks, clean_suggestions = control
        result["control"] = {
            "issues": len(clean.issues),
            "issues_grounded": sum(i.grounded for i in clean.issues),
            "checks": len(clean_checks),
            "suggestions": len(clean_suggestions),
            "suggestions_on_unchecked_positions": sum(not s.checked for s in clean_suggestions),
            "stats": run_stats(clean),
            "parts": [asdict(p) for p in clean.parts],
        }
    (args.out / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    (args.out / "report.md").write_text(render(result, args), encoding="utf-8")
    s, t = result["score"], result["together"]
    print(
        f"planted found {s['planted_found']}/{s['planted_total']} by the model, "
        f"{t['checks']['planted_found']} by the checks, {t['together']['planted_found']} by both; "
        f"oddities {s['oddities_found']}/{s['oddities_total']}, issues {s['issues']}, unmatched "
        f"{s['issues_unmatched']}; report: {args.out / 'report.md'}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
