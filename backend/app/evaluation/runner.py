"""Run the synthetic benchmark through the product's own path and write the report.

Each generated document is uploaded with :func:`app.services.documents.upload` (security checks,
extraction, normalization) and validated with :func:`app.services.runs.start` (every registered
check, as in the product), on in-memory storage. The columns no header maps (``boq`` bills: the
STLB-Bau key and the unit price components) are mapped at upload as a reviewer would map them
(:meth:`~app.evaluation.synthetic.SyntheticDocument.decisions`). The findings are then matched
against the ground truth (:mod:`app.evaluation.scoring`).

Output directory: ``documents/`` (the generated files), ``manifest.json`` (ground truth),
``report.json`` (every metric, per error kind, per variant, per document) and ``report.md``.
The ``boq`` corpus variant adds the metrics of :mod:`app.evaluation.boq_report` (per kind and
check, signals on unplanted rows).
"""

from __future__ import annotations

import hashlib
import json
import platform
import statistics
import tempfile
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from app.core.clock import SystemClock
from app.core.config import Settings
from app.core.ids import SequentialIdFactory
from app.evaluation import ablation, boq_report
from app.evaluation.boq_report import LABEL
from app.evaluation.scoring import (
    RISK_NOTE_RULES,
    RISK_NOTES_LINE,
    DocumentResult,
    Finding,
    Tally,
    findings_of,
    risk_notes_text,
    score_document,
)
from app.evaluation.synthetic import CorpusConfig, SyntheticDocument, generate_corpus
from app.models.dataset import Dataset
from app.models.document import Document
from app.repositories.base import IssueQuery
from app.repositories.memory import InMemoryDatabase, InMemoryUnitOfWorkFactory
from app.services import documents, runs
from app.services.workbench import Workbench, build_workbench
from app.storage.file_store import LocalFileStore
from app.validation.contracts.detector import DetectorCategory
from app.validation.planner import BaselinePlanner
from app.validation.registry.registry import DetectorRegistry

DISCLAIMER = (
    "Synthetic documents only: generated bills with injected errors. No real-world documents "
    "were evaluated, so these numbers say nothing about performance on real bills. The values "
    "are ratios over this generated set, not probabilities."
)


# Detector categories whose findings are rule findings; the others only signal.
RULE_CATEGORIES = frozenset({DetectorCategory.DETERMINISTIC, DetectorCategory.DOMAIN})


@dataclass(frozen=True)
class BenchmarkConfig:
    corpus: CorpusConfig = field(default_factory=CorpusConfig)
    k: int = 5
    profile_id: str = "boq"
    # boq variant: also measure each check by leaving it out (leave-one-out ablation) and the
    # review-budget baselines (app.evaluation.ablation)
    ablation: bool = False


def _classification(
    doc: SyntheticDocument, dataset: Dataset | None
) -> tuple[tuple[int, int], tuple[tuple[int, str, str], ...]]:
    recognized: dict[int, str] = {}
    if dataset is not None:
        for table in dataset.tables:
            for row in table.rows:
                recognized[row.source_row_number] = row.kind.value
    wrong = tuple(
        (row, kind, recognized.get(row, "missing"))
        for row, kind in sorted(doc.row_kinds.items())
        if recognized.get(row) != kind
        and not (kind == "blank" and row not in recognized)  # empty rows may be dropped
    )
    return (len(doc.row_kinds) - len(wrong), len(doc.row_kinds)), wrong


def benchmark_workbench(root: Path) -> Workbench:
    """The product's services on in-memory storage, with uploads stored under ``root``."""
    return build_workbench(
        Settings(data_dir=root, environment="test"),
        uow=InMemoryUnitOfWorkFactory(InMemoryDatabase()),
        files=LocalFileStore(root),
        ids=SequentialIdFactory(),
        clock=SystemClock(),
    )


def run_findings(wb: Workbench, dataset: Dataset) -> list[Finding]:
    """Validate ``dataset`` with every check of ``wb`` and return the findings in the
    register's order."""
    run = runs.start(wb, dataset.dataset_id)
    with wb.uow() as uow:
        issues = list(uow.issues.iter_all(IssueQuery(run_id=run["run_id"])))
    return findings_of(issues, dataset)


def without_check(wb: Workbench, detector_id: str) -> Workbench:
    """``wb`` with one check left out of its registry and its planner (every run checks with
    every registered check, so leaving a check out of the registry turns it off), on the same
    storage: a leave-one-out run of the ablation (:mod:`app.evaluation.ablation`)."""
    kept = DetectorRegistry(
        [wb.detectors.get(other) for other in wb.detectors.ids() if other != detector_id]
    )
    return replace(wb, detectors=kept, planner=BaselinePlanner(kept))


def _upload(
    wb: Workbench, doc: SyntheticDocument, profile_id: str
) -> tuple[Document, Dataset | None]:
    return documents.upload(
        wb,
        filename=doc.name,
        chunks=[doc.content],
        profile_id=profile_id,
        decisions=doc.decisions(),
    )


def _result(
    doc: SyntheticDocument,
    dataset: Dataset | None,
    findings: list[Finding],
    *,
    k: int,
    seconds: float,
    status: str,
) -> DocumentResult:
    classified, wrong = _classification(doc, dataset)
    return DocumentResult(
        document=doc,
        score=score_document(findings, doc.truths, k=k, noted_rows=doc.contingency_and_hourly_rows),
        classified=classified,
        misclassified=wrong,
        seconds=seconds,
        status=status,
    )


def evaluate(
    wb: Workbench,
    doc: SyntheticDocument,
    *,
    k: int,
    profile_id: str,
) -> DocumentResult:
    started = time.perf_counter()
    document, dataset = _upload(wb, doc, profile_id)
    findings = run_findings(wb, dataset) if dataset is not None else []
    seconds = time.perf_counter() - started
    return _result(
        doc, dataset, findings, k=k, seconds=seconds, status=document.processing_status.value
    )


def evaluate_ablation(
    wb: Workbench, doc: SyntheticDocument, *, k: int, profile_id: str, seed: int
) -> tuple[DocumentResult, ablation.BillMeasure]:
    """:func:`evaluate`, and the measurements of :mod:`app.evaluation.ablation`: the same upload
    validated again once per check with that check left out (:func:`without_check`), and the
    review-budget baselines. The time per document is that of the upload and the full run."""
    started = time.perf_counter()
    document, dataset = _upload(wb, doc, profile_id)
    findings = run_findings(wb, dataset) if dataset else []
    seconds = time.perf_counter() - started
    result = _result(
        doc, dataset, findings, k=k, seconds=seconds, status=document.processing_status.value
    )
    signals = signal_checks(wb)
    without = {
        detector_id: ablation.run_score(
            run_findings(without_check(wb, detector_id), dataset) if dataset else [],
            doc,
            signals,
        )
        for detector_id in wb.detectors.ids()
    }
    return result, ablation.measure_bill(
        doc, dataset, findings, without, signal_checks=signals, seed=seed
    )


def run_benchmark(config: BenchmarkConfig, out_dir: Path) -> dict[str, Any]:
    """Generate, evaluate and write everything to ``out_dir``; return the report."""
    began = time.perf_counter()
    corpus = generate_corpus(config.corpus)
    (out_dir / "documents").mkdir(parents=True, exist_ok=True)
    for doc in corpus:
        (out_dir / "documents" / doc.name).write_bytes(doc.content)
    _write_json(out_dir / "manifest.json", _manifest(config, corpus))
    with tempfile.TemporaryDirectory(prefix="twb-benchmark-") as scratch:
        wb = benchmark_workbench(Path(scratch))
        measures: list[ablation.BillMeasure] = []
        results: list[DocumentResult] = []
        for doc in corpus:
            if config.ablation:
                result, measure = evaluate_ablation(
                    wb, doc, k=config.k, profile_id=config.profile_id, seed=config.corpus.seed
                )
                measures.append(measure)
            else:
                result = evaluate(wb, doc, k=config.k, profile_id=config.profile_id)
            results.append(result)
        report = _report(config, results)
        if config.corpus.variant == "boq":
            report["boq"] = boq_sections(wb, config.profile_id, config, results)
            if config.ablation:
                report["boq"]["ablation"] = ablation.build(
                    measures,
                    checks=wb.detectors.ids(),
                    signal_checks=signal_checks(wb),
                    seed=config.corpus.seed,
                )
    report["timing"]["total_seconds"] = round(time.perf_counter() - began, 1)
    _write_json(out_dir / "report.json", report)
    (out_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def signal_checks(wb: Workbench) -> frozenset[str]:
    """The registered checks that only signal (statistical, machine learning, semantic, ...)."""
    return frozenset(
        spec.detector_id for spec in wb.detectors.specs() if spec.category not in RULE_CATEGORIES
    )


def boq_sections(
    wb: Workbench, profile_id: str, config: BenchmarkConfig, results: Sequence[DocumentResult]
) -> dict[str, Any]:
    return boq_report.build(
        results,
        config.corpus.kinds,
        registered=wb.detectors.ids(),
        signal_checks=signal_checks(wb),
        defaults=wb.profiles.get(profile_id).detector_defaults,
    )


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _manifest(config: BenchmarkConfig, corpus: list[SyntheticDocument]) -> dict[str, Any]:
    return {
        "seed": config.corpus.seed,
        "corpus": config.corpus.describe(),
        "documents": [
            {
                "name": doc.name,
                "language": doc.language,
                "format": doc.format,
                "sha256": hashlib.sha256(doc.content).hexdigest(),
                "data_rows": doc.data_rows,
                **({"features": doc.features} if doc.features else {}),
                **(
                    {"column_fields": {str(c): f for c, f in sorted(doc.column_fields.items())}}
                    if doc.column_fields
                    else {}
                ),
                "row_kinds": {str(row): kind for row, kind in sorted(doc.row_kinds.items())},
                "errors": [asdict(truth) | {"kind": truth.kind.value} for truth in doc.truths],
            }
            for doc in corpus
        ],
    }


def _report(config: BenchmarkConfig, results: list[DocumentResult]) -> dict[str, Any]:
    overall = Tally()
    by_variant: defaultdict[str, Tally] = defaultdict(Tally)
    by_kind: dict[str, dict[str, int]] = {
        kind.value: {"injected": 0, "detected": 0, "expected_rule": 0, "localized": 0}
        for kind in config.corpus.kinds
    }
    missed: list[dict[str, object]] = []
    false_positives: list[dict[str, object]] = []
    misclassified: list[dict[str, object]] = []
    for result in results:
        doc = result.document
        for tally in (overall, by_variant[f"{doc.language}-{doc.format}"]):
            tally.add(
                result.score,
                rows=doc.data_rows,
                classified=result.classified,
                seconds=result.seconds,
            )
        for outcome in result.score.outcomes:
            counts = by_kind[outcome.truth.kind.value]
            counts["injected"] += 1
            counts["detected"] += outcome.detected
            counts["expected_rule"] += outcome.expected_rule
            counts["localized"] += outcome.localized
            if not outcome.detected or not outcome.expected_rule:
                missed.append(
                    {
                        "document": doc.name,
                        "error_id": outcome.truth.error_id,
                        "kind": outcome.truth.kind.value,
                        "row": outcome.truth.row,
                        "change": outcome.truth.change,
                        "detected": outcome.detected,
                        "rules_found": list(outcome.rules),
                    }
                )
        false_positives.extend(
            {
                "document": doc.name,
                "rule_id": f.rule_id,
                "detector_id": f.detector_id,
                "rows": sorted(f.rows),
                "title": f.title,
            }
            for f in result.score.false_positives
        )
        misclassified.extend(
            {"document": doc.name, "row": row, "intended": intended, "recognized": recognized}
            for row, intended, recognized in result.misclassified
        )
    seconds = [r.seconds for r in results]
    timing = {
        "median_seconds_per_document": round(statistics.median(seconds), 4) if seconds else None,
        "max_seconds_per_document": round(max(seconds), 4) if seconds else None,
        "rows_per_second": round(overall.rows / overall.seconds) if overall.seconds else None,
        "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
    }
    return {
        "label": LABEL,
        "disclaimer": DISCLAIMER,
        "variant": config.corpus.variant,
        "seed": config.corpus.seed,
        "k": config.k,
        "ablation": config.ablation,
        "profile_id": config.profile_id,
        "corpus": config.corpus.describe(),
        "synthetic": overall.metrics(),
        "real_world": None,
        "timing": timing,
        "by_error_kind": by_kind,
        "by_variant": {name: tally.metrics() for name, tally in sorted(by_variant.items())},
        "documents": [
            {
                "name": r.document.name,
                "status": r.status,
                "rows": r.document.data_rows,
                "injected": [t.kind.value for t in r.document.truths],
                "findings": r.score.findings,
                "false_positives": len(r.score.false_positives),
                "correct_risk_notes": len(r.score.correct_notes),
                "detected": sum(o.detected for o in r.score.outcomes),
                "seconds": round(r.seconds, 4),
            }
            for r in results
        ],
        "missed_or_misnamed_errors": missed,
        "false_positives": false_positives,
        "misclassified_rows": misclassified,
        "risk_notes": {
            "correct": overall.correct_notes,
            "false": sum(
                1
                for r in results
                for f in r.score.false_positives
                if (f.detector_id, f.rule_id) in RISK_NOTE_RULES
            ),
        },
    }


def risk_notes(report: dict[str, Any]) -> str:
    """The risk notes line of a report (``report["risk_notes"]``, see scoring)."""
    notes = report["risk_notes"]
    return risk_notes_text(notes["correct"], notes["false"])


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def recall_within_line(budget: int) -> str:
    """The report's label for recall in the first ``budget`` findings: the register's order,
    in which a correct risk note on an unplanted row takes no place (see ``scoring``)."""
    return (
        f"Recall in first {budget} findings (register order, correct risk notes on unplanted "
        "rows take no place)"
    )


def render_markdown(report: dict[str, Any]) -> str:
    if report.get("variant") == "boq":
        text = boq_report.render(report)
        if "ablation" in report["boq"]:
            text += "\n".join(ablation.render(report["boq"]["ablation"])) + "\n"
        return text
    m = report["synthetic"]
    lines = [
        "# Synthetic benchmark report",
        "",
        f"{LABEL}.",
        "",
        report["disclaimer"],
        "",
        f"Seed `{report['seed']}`, profile `{report['profile_id']}`, "
        f"{report['corpus']['documents_per_variant']} documents per language and format. "
        "Regenerate with `python -m app.evaluation` (see `--help`).",
        "",
        "## Synthetic documents",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| **F2 at 50 (main score)** | **{_fmt(m['f2_at_50'])}** |",
        f"| Precision at 50 (mean) | {_fmt(m['mean_precision_at_50'])} |",
        f"| Recall at 50 (mean) | {_fmt(m['mean_recall_at_50'])} |",
        f"| Documents | {m['documents']} |",
        f"| Data rows | {m['rows']} |",
        f"| Injected errors | {m['injected_errors']} |",
        f"| Findings | {m['findings']} |",
        f"| Precision | {_fmt(m['precision'])} |",
        f"| Recall | {_fmt(m['recall'])} |",
        f"| {recall_within_line(20)} | {_fmt(m['recall_at_20'])} |",
        f"| {recall_within_line(50)} | {_fmt(m['recall_at_50'])} |",
        f"| F1 | {_fmt(m['f1'])} |",
        f"| Precision at {report['k']} | {_fmt(m['precision_at_k'])} |",
        f"| False positives per 1,000 rows | {_fmt(m['false_positives_per_1000_rows'])} |",
        f"| {RISK_NOTES_LINE} | {risk_notes(report)} |",
        f"| Detected with the expected rule | {_fmt(m['detected_with_expected_rule'])} |",
        f"| Cell localization | {_fmt(m['cell_localization'])} |",
        f"| Row classification accuracy | {_fmt(m['row_classification_accuracy'])} |",
        f"| Median time per document (s) | "
        f"{_fmt(report['timing']['median_seconds_per_document'])} |",
        f"| Rows per second | {_fmt(report['timing']['rows_per_second'])} |",
        "",
        f"Timing machine: {report['timing']['machine']}.",
        "",
        "## Real-world documents",
        "",
        "None evaluated: no labelled real bills are available. Synthetic results must not be "
        "read as real-world performance.",
        "",
        "## By error kind",
        "",
        "| Error kind | Injected | Detected | With expected rule | Cell localized |",
        "| --- | --- | --- | --- | --- |",
    ]
    for kind, counts in report["by_error_kind"].items():
        lines.append(
            f"| `{kind}` | {counts['injected']} | {counts['detected']} | "
            f"{counts['expected_rule']} | {counts['localized']} |"
        )
    lines += [
        "",
        "## By language and format",
        "",
        "| Variant | Documents | Rows | Injected | Detected | Findings | False positives |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, v in report["by_variant"].items():
        lines.append(
            f"| {name} | {v['documents']} | {v['rows']} | {v['injected_errors']} | "
            f"{v['detected_errors']} | {v['findings']} | {v['false_positive_findings']} |"
        )
    lines += ["", "## Missed or misnamed errors", ""]
    if report["missed_or_misnamed_errors"]:
        lines += [
            "| Document | Kind | Row | Change | Rules found |",
            "| --- | --- | --- | --- | --- |",
        ]
        for e in report["missed_or_misnamed_errors"][:30]:
            found = ", ".join(e["rules_found"]) or "none"
            lines.append(
                f"| {e['document']} | `{e['kind']}` | {e['row']} | {e['change']} | {found} |"
            )
    else:
        lines.append("None.")
    lines += ["", "## False positives", ""]
    if report["false_positives"]:
        lines += ["| Document | Rule | Rows | Title |", "| --- | --- | --- | --- |"]
        for f in report["false_positives"][:30]:
            rows = ", ".join(map(str, f["rows"])) or "table"
            lines.append(f"| {f['document']} | `{f['rule_id']}` | {rows} | {f['title']} |")
    else:
        lines.append("None.")
    lines += [
        "",
        "## Definitions",
        "",
        "F2 at 50, the main score, weighs recall four times as much as precision (F-beta, "
        "beta = 2) over the first 50 findings of each document in the reviewer's order: "
        "precision at 50 divides the true positives among them by the findings shown, recall "
        "at 50 the injected errors they match by the document's injected errors; F2 and both "
        "are averaged over the documents with injected errors. "
        "A finding is a true positive when it highlights a row where reporting an injected error "
        "is correct: the error's own row, or a total the error throws off (a wrong net total also "
        "breaks the tax and gross checks). Precision at K uses the order a reviewer sees "
        "(spelling and text-style findings last, otherwise severity, then position) and "
        "divides by the number of findings shown, at most K; it "
        "is averaged over documents with findings. Recall in the first 20 (or 50) findings "
        "divides the injected errors that the first 20 (or 50) findings in that order match by "
        "all injected errors. Like precision at K, it passes over correct risk notes on "
        "unplanted rows, which take no place in the list; a wrong risk note keeps its place and "
        "matches nothing. Cell localization counts detected errors whose wrong cell is "
        "highlighted. See `backend/app/evaluation/scoring.py`.",
        "",
    ]
    return "\n".join(lines)
