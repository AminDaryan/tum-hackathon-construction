"""``python -m app.evaluation``: run the synthetic benchmark and print the report.

``--variant boq`` runs the BoQ variant (bills that behave like real ones, with planted errors of
all seven anomaly types); ``--inject-into <folder>`` plants the same kinds into the bills in that
folder instead (:mod:`app.evaluation.inject`). ``--ablation`` also measures each check of the BoQ
variant by leaving it out, with the review-budget baselines (:mod:`app.evaluation.ablation`).
``--answer-key KEY.json --clean FILE`` scores every check against a bill with hand-planted
faults (:mod:`app.evaluation.answer_key`).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.evaluation.answer_key import render as render_answer_key
from app.evaluation.answer_key import run_answer_key
from app.evaluation.inject import InjectConfig, run_injection, summary
from app.evaluation.runner import BenchmarkConfig, render_markdown, run_benchmark
from app.evaluation.synthetic import BOQ_MAX_ERRORS, BOQ_SEED, BoqSettings, CorpusConfig


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.evaluation", description="Synthetic benchmark (brief Part L)."
    )
    parser.add_argument(
        "--variant",
        choices=("standard", "boq"),
        default="standard",
        help="corpus variant (default: %(default)s)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help=f"default: {CorpusConfig.seed} (standard), {BOQ_SEED} (boq)",
    )
    parser.add_argument(
        "--documents",
        type=int,
        default=CorpusConfig.documents_per_variant,
        help="documents per language and format (standard), or bills (boq); default: %(default)s",
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=None,
        help=f"per document; default: {CorpusConfig.max_errors} (standard), {BOQ_MAX_ERRORS} (boq)",
    )
    parser.add_argument(
        "--positions",
        type=int,
        nargs=2,
        metavar=("MIN", "MAX"),
        default=BoqSettings.positions,
        help="positions per bill of the boq variant (default: %(default)s)",
    )
    parser.add_argument(
        "--inject-into",
        type=Path,
        default=None,
        metavar="FOLDER",
        help="plant errors into the XLSX and CSV bills in FOLDER, in memory (the files are not "
        "changed), instead of generating a corpus",
    )
    parser.add_argument(
        "--ablation",
        action="store_true",
        help="boq variant: also measure each check by leaving it out, with the review-budget "
        "baselines",
    )
    parser.add_argument(
        "--answer-key",
        type=Path,
        default=None,
        metavar="KEY_JSON",
        help="score every check against the bill the answer key names (needs --clean)",
    )
    parser.add_argument(
        "--clean",
        type=Path,
        default=None,
        metavar="FILE",
        help="the clean original of the --answer-key bill: hits it also has are not credited",
    )
    parser.add_argument(
        "--bill",
        type=Path,
        default=None,
        metavar="FILE",
        help="the faulty bill of --answer-key (default: the key's 'file', next to the key)",
    )
    parser.add_argument("--k", type=int, default=5, help="K for precision at K")
    parser.add_argument(
        "--out", type=Path, default=Path("var/benchmark"), help="default: %(default)s"
    )
    args = parser.parse_args(argv)
    if args.answer_key is not None:
        if args.clean is None:
            parser.error("--answer-key needs --clean")
        try:
            scored = run_answer_key(
                args.answer_key,
                clean_path=args.clean,
                bill_path=args.bill,
                out_dir=args.out,
                seed=args.seed if args.seed is not None else BOQ_SEED,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(render_answer_key(scored))
        print(f"Report written to {args.out / 'answer-key-report.md'}")
        return
    if args.inject_into is not None:
        config = InjectConfig(
            seed=args.seed if args.seed is not None else BOQ_SEED,
            max_errors=args.max_errors if args.max_errors is not None else BOQ_MAX_ERRORS,
            k=args.k,
        )
        try:
            injected = run_injection(args.inject_into, config, args.out)
        except ValueError as exc:
            parser.error(str(exc))
        print(summary(injected))
        print(f"Report written to {args.out / 'inject-report.md'}")
        return
    boq = args.variant == "boq"
    corpus = CorpusConfig(
        seed=args.seed if args.seed is not None else (BOQ_SEED if boq else CorpusConfig.seed),
        documents_per_variant=args.documents,
        max_errors=args.max_errors
        if args.max_errors is not None
        else (BOQ_MAX_ERRORS if boq else CorpusConfig.max_errors),
        variant=args.variant,
        boq=BoqSettings(positions=(args.positions[0], args.positions[1])),
    )
    if args.ablation and not boq:
        parser.error("--ablation needs --variant boq")
    report = run_benchmark(
        BenchmarkConfig(corpus=corpus, k=args.k, ablation=args.ablation), args.out
    )
    print(render_markdown(report))
    print(f"Written to {args.out}")


if __name__ == "__main__":
    main()
