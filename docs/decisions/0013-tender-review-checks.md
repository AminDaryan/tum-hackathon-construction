# 0013: The tender review: what an estimator checks before pricing, as signals

Status: accepted (2026-11-21). Takes up, for bills of quantities, semantic checks that
[ADR 0008](0008-deferred-to-phase-2.md) deferred, under the rule of
[ADR 0010](0010-boq-anomaly-detection.md): comparisons and wording only signal.

Status note (2026-11-21, merge with step B2): one condition, one reporting check
([ADR 0007](0007-condition-ownership.md)), applied as below. B2 had built a typo check under
the same id, `domain.boq_typos`; the two are one check now, this one (version 1.1.0), whose
`rare_variant` uses B2's matcher (a word of at least nine letters used once, one letter
replaced, added or dropped, or two neighbours swapped, from a word the bill uses at least three
times; pairs that are usually two real words are ignored), because on the planted-fault test
bill it found both planted slips and flagged none of the rows that must stay clean, where the
first matcher found neither. `misplaced_item` gives an item up where
`deterministic.hierarchy` compares its number with its section's, as the consequence below
planned. `domain.boq_description_clarity` leaves to `domain.boq_clauses` the wording that check
reports: "nach Bedarf" and "nach Erfordernis" (`vague_wording`), "nach Aufwand" in a lump sum
(`open_lump_sum`) and "einschl. aller erforderlichen ..." (`vague_wording`, which leaves small
material out). The checks' finding categories, proposed in `main` (numbering an Omission,
unclear descriptions and contradictions within an item an Ambiguity, typing slips an Error),
gain two rule entries as B2 categorises the same kinds: `open_decision` is a Change order
opportunity, like `domain.boq_clauses`' deferred decisions, and `misplaced_item` an Error, like
`deterministic.hierarchy`'s item outside its section. The owner is asked to confirm them.

## Context

Bills now arrive as GAEB files, spreadsheets, printed PDFs and scans
([ADR 0011](0011-pdf-bills-and-excel-export.md), [ADR 0012](0012-ocr-for-scanned-pdfs.md)).
The 15 checks before this record find arithmetic, structure and standard-text-key conflicts;
none reads what the items say. A tender estimator (Kalkulator) reads a bill before pricing it
and sends questions to the client during the bidding period (Bieterfragen). The estimator looks
for:

* **missing items**: numbers skipped, items filed in the wrong section, section headings with
  nothing below them;
* **unclear descriptions**: VOB/A § 7 (1) asks for a description that is clear and complete,
  that every bidder understands alike, and that puts no unusual risk on the bidder;
* **contradictions**: a short text and a long text that name different things, or a text that
  contradicts the item's unit, quantity or type;
* **typing slips**.

A bill read from a PDF or a scan can also carry extraction errors (a line lost, a word read
wrongly), and they show up in the same way.

## Decision

Four checks join the BoQ profile's baseline plan (profile 1.4.0, `baseline_detectors`), so
every run on a bill gets them without configuration:

| Check | Rules | Finding |
| --- | --- | --- |
| `domain.boq_numbering` (statistical) | `numbering_gap` (low), `misplaced_item`, `empty_section` (medium) | suspected anomaly |
| `domain.boq_description_clarity` (semantic) | `placeholder_text`, `relative_without_base` (medium); `open_scope`, `open_decision`, `short_text_only` (low); one summary per table for `catch_all_wording` (info) and `bidder_input_required` (info, needs external context) | semantic warning |
| `domain.boq_contradictions` (semantic) | `spec_conflict`, `billing_unit_conflict`, `item_type_conflict` (medium); `quantity_text_conflict` (low) | semantic warning |
| `domain.boq_typos` (semantic) | `repeated_word`, `known_misspelling`, `rare_variant` (low) | semantic warning |

The [detector catalogue](../architecture/detector-catalogue.md) lists every parameter.

* **Signals, not verdicts.** No rule confirms an error. Each finding says what it read, and its
  suggested action is the question to ask the client. None changes a total or stops a run.
* **Plain phrases.** The wording lists (placeholders, open scope, catch-all wording, and the
  rest) are profile-tunable plain phrases in German and English, never regular expressions
  from a profile. They are matched as whole words, ignoring case, over the whole text, long
  text included. `app.core.patterns` reads only a 500-character window, and long texts are
  longer than that.
* **The bill is its own reference.** No dictionary and no catalogue. A general dictionary does
  not know construction compounds (`Kalksandstein-Planstein`, `Dünnbettmörtel`) and would bring
  in a word list with its own licence. So a typing slip is a word used once that differs by one
  letter from a word the bill uses often, and a numbering gap is a step missing from the
  group's own most common step. Without a dictionary the check cannot say which of two
  spellings is right, so `rare_variant` names both.
* **Only one item and its own texts.** Contradictions are found within an item: its short text
  against its long text (`DN 125` and `DN 100`, `C20/25` and `C25/30`), its text against its
  unit by dimension, through the profile's unit vocabulary, against its quantity, and against
  whether it counts toward the total. A long text that also repeats the short text's value is
  not a contradiction (a reducer `DN 150` to `DN 100`).
* **Noise is bounded.** The checks were tuned on the 43 bills in `Sample BoQ Dataset/` (GAEB DA
  XML, GAEB 90, PDF and scans). These are left out:
  * wording that is common and not wrong on its own, which gets one summary per table instead
    of one finding per item;
  * inflected forms, a joining `s`, `ie`/`ei` swaps and replaced letters, which are usually
    two real words;
  * doubled articles (`das das`);
  * time-based items (daywork, plant hire), whose short texts are short by nature;
  * contingency items "mit GB", which count toward the total on purpose;
  * compound units (`m² x Woche`);
  * parent sections, when the section nested inside them is the empty one.

  The final run found 280 findings in the 43 bills: 3 bills have none, the median is 3, and one
  bill has 45 (38 bare short texts, in a bill written in long texts). Spot checks found real
  problems: diameters and concrete classes that differ between short and long text, `???` left
  in a text, a section with no items, an item paid per week but measured in pieces, `nach
  nach` and `und und`, and misspellings.
* **The benchmark measures rule checks.** The generated bills are written without regard to
  wording, so the benchmark plan (`evaluation.runner.plan_with`) is the baseline plan without
  its signal checks. A benchmark step can still add them back.

**Not adopted.**

* A spell checker with a German dictionary, because of compounds and licensing (above).
* A language model reading the texts. No model is on the allow-list, and under ADR 0010 a
  local model only explains findings; it never raises them.
* Checks across items (an item that contradicts another, scope missing from the whole bill).
  They need the text comparisons of step B3 and the judgement of someone who knows the
  project.

## Consequences

* `misplaced_item` (an item whose number does not start with its section's number) overlaps a
  rule check that step B2 plans ("an OZ outside its Titel"). When B2 confirms that condition,
  `misplaced_item` gives it up, because each condition has one reporting detector
  ([ADR 0007](0007-condition-ownership.md)). Done with B2's merge (status note).
* Wording in other languages needs profile phrases. Words the bill misspells the same way every
  time are not found.
* A numbering gap is often an item deleted on purpose, so the finding asks; it does not
  accuse.
* OCR slips are reported as typing slips. That is useful, because they are extraction errors to
  check against the page.

## Amendment of 2026-11-21

Every validation now runs every registered check ([ADR 0010](0010-boq-anomaly-detection.md),
amendment of 2026-11-21): the profile's `baseline_detectors` is gone, and the benchmark no
longer drops signal checks from its plan (`plan_with` is gone). It counts their findings on
unplanted rows apart from rule findings, as before.
