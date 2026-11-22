# Critique: boq-domain

**Status:** Applied to the contracts (decision table, new row kinds, value markers, totals rules, BoQ wording). The normalization and detector parts are specified in NEXT_STEPS.md but not implemented yet.

## Overall

The generic split is sound: classification wording lives in the profile, the core has no construction terms, and the model edits made during this review (multi-row headers, section_path and closes_section_id, counts_toward_totals, the duplicate-mapping guard, the percent quantity_factor) close several gaps. Reviewed against the tree as of about 21:00 UTC; those files changed while the review ran, and the suite is green (126 passed). The BoQ contract is not yet safe to build on: precedence between patterns, section codes and values is undefined; common German and UK total, VAT, carry-forward, summary and discount lines are misclassified; and lump sums, unpriced BoQs, 'Incl.'-type markers and optional items will flood the baseline detectors with false confirmed violations. Fix the decision table, add SUMMARY_LINE/ADJUSTMENT kinds, value markers and conditional requirements, and add a golden label-to-kind test before the normalization and reconciliation detectors are written.

## 1. [high] backend/app/models/profile.py RowClassificationRules (docstring order, item_value_fields, section_code_pattern) and backend/app/normalization/builder.py contract docstring

**Problem:** The contract lists the pattern order but never says how pattern matches, section_code_pattern and value presence (item_value_fields) interact, or which field section_code_pattern is tested on. Both obvious readings fail on boq.yaml (verified by running the regexes). (a) Patterns or codes first: section_patterns match priced items such as 'Chapter 8 traffic management', 'Section 278 highway works', 'Part L air tightness testing', 'Trade waste disposal' and 'Group planting; shrubs as schedule'. section_code_pattern matches item numbers '1.01'/'12.05' (FIDIC/World Bank), '1.1'/'2.10' (simple Excel LVs), '01.10' (OZ mask 11PPI) and running numbers '7'. Those items become SECTION rows, drop out of every sum and restart section_path, so the enclosing subtotal is reported as a confirmed violation. The pattern also misses 3-level GAEB sections such as '01.02.03'. (b) Values first: every amount-only row whose label no pattern knows ('zzgl. 19 % MwSt.', 'Nettosumme', 'Page 2/1', 'Nachlass 5 %', Zusammenstellung lines) becomes an ITEM. Each one gets 3-4 missing-value violations and its amount is added into the grand-total sum.

**Fix:** Write a decision table into the RowClassificationRules docstring and the build_dataset contract. 1) BLANK. 2) Total and carry patterns apply only when quantity and unit_price are empty: a row with a quantity or a rate is never a total. 3) SECTION (by pattern or code) only when no item_value_field has a value. 4) ITEM needs quantity or unit_price, or unit plus line_total (lump sums). 5) Anything else is TEXT plus an ExtractionWarning 'unclassified_amount_row' (needs_review=True). Also record rows where patterns of two kinds match. Add section_code_field, and accept a code as a section only if it is a strict prefix of following item codes. This is a domain-neutral hierarchical-identifier rule that handles any depth or OZ mask. Pin the behaviour with a golden test of (label, filled fields) -> kind for boq.yaml.

## 2. [high] backend/app/profiles/boq.yaml row_classification.gross_total_patterns / tax_patterns / grand_total_patterns

**Problem:** Verified in the documented order. Gross totals written with 'inkl./incl.' become GRAND_TOTAL: 'Gesamtsumme inkl. MwSt.', 'Gesamtbetrag inkl. 19 % USt.', 'Angebotssumme inkl. MwSt.' and 'Grand Total (incl. VAT)'. 'Summe inkl. MwSt.' becomes SUBTOTAL. The grand-total check then reports the whole VAT (19-20% of the contract value) as a confirmed violation with financial impact. The most common VAT line forms match nothing: 'zzgl. 19 % MwSt.', '+ 19 % MwSt.', '19 % MwSt.', 'Add VAT at 20%', '20% VAT', 'GST 10%'. 'Summe MwSt.' becomes SUBTOTAL. Net grand totals 'Summe LV', 'Summe Leistungsverzeichnis', 'Summe aller Titel' and 'Summe gesamt' fall into the catch-all '^\s*summe\b' and become SUBTOTAL, so they are compared with the last section only. 'Gesamt', 'Nettosumme', 'Total (excl. VAT)', 'Contract Sum' and 'Total tender sum' match nothing.

**Fix:** Gross (checked first): add '\b(inkl\.?|inklusive|einschl\.?|einschlie(ß|ss)lich|incl(\.|uding|usive(\s+of)?)?)\s*\(?\s*(\d+([.,]\d+)?\s*%\s*)?(mwst|mw\.?-?st|ust|umsatzsteuer|mehrwertsteuer|vat|gst|tax)\b' and '\bbrutto\b'. Tax (after gross, unanchored): '\b(zzgl\.?|zuzüglich|add:?|plus|\+)?\s*(\d+([.,]\d+)?\s*%\s*)?(mwst|mw\.?-?st\.?|ust\.?|umsatzsteuer|mehrwertsteuer|vat|gst|sales\s+tax)\b'. Grand (before subtotal): '^\s*summe\s+(lv|leistungsverzeichnis|angebot|aller\s+titel|gesamt|zusammenstellung)\b', '^\s*(gesamt|nettosumme|netto-?angebotssumme)\s*:?\s*$', '^\s*total\s*\(?\s*(excl(\.|uding)?|exclusive\s+of|net\s+of)\s+(vat|tax)' and '^\s*(total\s+)?(contract|tender)\s+sum\b'. Guard the 'gesamtsumme|...' pattern with (?!\s+(titel|untertitel|los|abschnitt)). Add every one of these labels to the golden classification test.

## 3. [high] backend/app/profiles/boq.yaml fields (all six required: true) and backend/app/models/profile.py SemanticField.required / required_row_kinds

**Problem:** Every ITEM must carry item code, description, quantity, unit, unit price and line total, and the model cannot express conditional requirements. The planned missing-values detector will therefore emit confirmed violations on legitimate rows:
- UK preliminaries and lump sums: unit 'Item', quantity and rate blank, amount only. A prelims bill typically has 50-150 such rows.
- Provisional sums and prime cost (PC) sums.
- Rate-only and 'nur EP' items, which by definition have no GP, even when the not-in-totals rule recognises them.
- Unpriced tender BoQs (LV-Blankett), the normal state of a client's BoQ: EP and GP are empty on every row, giving 2 violations per item.

**Fix:** Add generic conditions to SemanticField, for example required_unless: [{unit_dimension: [lump_sum]}, {counts_toward_totals: false}, {marker: [included_elsewhere, rate_only, nil]}]. Also add required_scope: always | when_column_populated, where a mapped but entirely empty column yields one table-level info finding ('column not filled') instead of per-row violations. In boq.yaml: quantity and unit_price required unless lump_sum; line_total required unless the row does not count toward totals; unit_price and line_total only when the column is populated.

## 4. [high] backend/app/models/values.py ParseStatus / CellValue, backend/app/models/profile.py (no marker vocabulary) and LocaleSettings

**Problem:** BoQs routinely put conventional tokens in numeric columns: UK 'Incl.', 'Included', 'Nil', '-', 'N/A', 'By others', 'Rate only'; German 'inkl.', 'enthalten', 'entfällt', 'bauseits', 'nur EP', '-,--', and 'psch' in the Menge column. The canonical model can only mark these FAILED. The data-type and numeric-validity detectors will then report them as confirmed rule violations; priced UK prelims bills are full of 'Incl.'. Reconciliation also cannot tell 'included elsewhere' from 'missing'. Parenthesised amounts such as '(1.234,00)' mean 'not in total' in German LV printouts but 'negative' in accounting. LocaleSettings cannot say which, so an accounting-style parser flips the sign and the line-total check fails.

**Fix:** Add a profile value_markers vocabulary: token lists mapped to generic meanings (nil, included_elsewhere, not_applicable, rate_only, lump_sum), scoped by field role and applied by normalization. In the canonical model add ParseStatus.MARKER plus Cell.marker; the raw text stays unchanged and no number is invented. Detectors: type and numeric checks skip markers; line_total abstains; totals treat nil and included_elsewhere as contributing nothing (not as missing); rate_only sets counts_toward_totals to False. Add LocaleSettings.parenthesized_numbers: negative | ambiguous, set to ambiguous for BoQ so these cells become AMBIGUOUS. Do this now: ParseStatus and CellValue are persisted, exported and rendered by the frontend.

## 5. [high] backend/app/profiles/boq.yaml not_in_totals_patterns / item_type field; backend/app/models/profile.py RowClassificationRules.not_in_totals_patterns; backend/app/models/dataset.py RowClassification.counts_toward_totals

**Problem:** Tested against realistic markers:
- 'Bedarfsposition mit GB' is excluded, although the GAEB 'mit Gesamtbetrag' variant is added to the total, so the subtotal fails by that position's GP.
- 'Alternativ zu Pos. 01.02.0030' and 'Option 2: upgrade to oak flooring' are counted.
- Positionsart column codes 'A', 'B', 'E', 'W', 'BoGB' and 'Alt.' are counted.
- Markers written in the GP/Amount cell ('nur EP', 'Alt.', 'Bedarf') or in the first Langtext line are never searched.
- Section-level exclusion is not propagated to the section's items or its subtotal: a Titel 'Bedarfspositionen'/'Wahlpositionen', or a UK 'Schedule of optional items - not included in the tender sum'. The grand total then fails.
A single exclude list with a bool result cannot express 'counted' exceptions or 'unknown'.

**Fix:** Replace the list with ordered first-match rules {rule_id, pattern, applies_to: label|category|amount_text|continuation_text, counts_toward_totals: true|false|null}. For example 'bedarfs\w*\s+mit\s+(gb|gesamtbetrag)' -> true comes before 'bedarfs\w*' -> null, and '^(a|alt\.?|w|e|bogb)$' applies to the category field only. Make counts_toward_totals bool | None. With None the subtotal detector tests both hypotheses and reports needs_external_context instead of a confirmed violation. Propagate a SECTION row's result to every row in its section_path, including its subtotal. Add a test table of markers.

## 6. [high] backend/app/models/dataset.py RowKind / TOTAL_ROW_KINDS and backend/app/profiles/boq.yaml row_classification

**Problem:** Standard closing blocks restate totals that are defined elsewhere:
- German 'Zusammenstellung': '01 Erdarbeiten 12.345,00', '02 ...', then 'Summe netto'.
- UK Collection: 'Page 2/1 £12,345.67', 'Page 2/2 ...'.
- UK Summary: 'Bill No. 2 Substructure £250,000', 'Total carried to Form of Tender'.
No existing kind fits. Code '01' with an amount becomes either SECTION (a duplicate section that is never cross-checked) or ITEM. As ITEM it gets 3 missing-value violations, and the recap is added to the grand-total sum, so the net total is reported off by 100% of itself. 'Page 2/1' becomes ITEM. 'Bill No. 2 ...' becomes SECTION by keyword, so a Summary sheet has no items and its tender total cannot be reconciled. Labelling these lines SUBTOTAL instead doubles any sum of subtotals. Discount lines between net and gross ('abzgl. 3 % Nachlass', 'Skonto 2 %', 'Less discount 2.5%') match nothing, and 'Summe nach Nachlass' becomes SUBTOTAL, so net + VAT never equals gross.

**Fix:** Add generic kinds SUMMARY_LINE (restates a total defined elsewhere; never an item, never summed with items) and ADJUSTMENT (signed modification of a total such as a discount or surcharge). In the profile, add summary_block_patterns ('^\s*(zusammenstellung|kostenzusammenstellung|collection|summary|general\s+summary|grand\s+summary)\b'), which switch amount rows to SUMMARY_LINE until the next total, and adjustment_patterns (nachlass|preisnachlass|rabatt|skonto|discount|rebate). Grand and gross detectors: reconcile against counted items and, separately, against summary lines; cross-check each summary line with its section subtotal by code; compute gross = net + adjustments + tax.

## 7. [high] backend/app/profiles/boq.yaml subtotal_patterns / carry_forward_patterns and the order in the RowClassificationRules docstring (backend/app/models/profile.py)

**Problem:** Labels that end in a total word hit section_patterns: 'Section 2 Total', 'Bill No. 3 Total', 'Titel 01 Summe' and 'Los 1 gesamt' become SECTION. The section total is then never checked, and under values-first it is added into the grand total. 'Substructure Total' and the German compounds 'Untertitelsumme', 'Lossumme', 'Bereichssumme' and 'Abschnittssumme' match nothing. Carry-forward is checked after subtotal, so page running totals ('Summe Übertrag', 'Sub-total carried forward', 'Summe Seite 3') become SUBTOTAL. Whenever a section spans pages they are reconciled against the section and fail as a confirmed violation. 'Page total' and 'Seitensumme' match nothing.

**Fix:** Check carry_forward first; this is domain-neutral, since a carried running total is never a scope total. Add '\bsumme\s+(übertrag|seite\s*\d*)\b', '^\s*seitensumme\b' and '\b(page\s+total|total\s+(this\s+)?page|to\s+collection)\b'. Add subtotal patterns '^\s*(section|bill|part|trade|element|title|group|titel|untertitel|los|abschnitt|gewerk|bereich|kapitel)\b.{0,80}\b(total|summe|gesamt)\s*:?\s*$' and '^\s*\w*summe\b', both after grand and gross, with 'nettosumme' moved into the grand patterns first.

## 8. [high] backend/app/models/dataset.py MappingMethod.HEADER_CONTAINS / Table._consistent; backend/app/profiles/boq.yaml header_synonyms; backend/app/normalization/builder.py

**Problem:** The header matching rules are unspecified, while the synonyms include 2-3 letter tokens and words contained in other fields' headers. A naive substring 'contains' match (verified) maps:
- 'Bemerkung' and 'Kommentar' -> unit (they contain 'me');
- 'Positionsart' and 'Pos.-Art' -> both item_code and item_type;
- 'Prozent' -> item_code (contains 'oz'); 'Zeichnungs-Nr.' -> item_code;
- 'Gesamtpreis', 'Total price' and 'Preis GP' -> both line_total and unit_price;
- 'Item description' -> both item_code and description.
GAEB-style exports with both Kurztext and Langtext columns map two columns to description by exact match. Billing layouts 'LV-Menge | Abrechnungsmenge | EP | GP' map two columns to quantity. Table now rejects duplicate mappings, so ingestion either errors or drops a column arbitrarily. If it keeps LV-Menge, every billed line total looks wrong. Two-row headers (for example 'Preis' merged over 'EP | GP') have no composition rule.

**Fix:** Specify the matching rules in the profile model and the build_dataset contract:
- normalize headers (NFKC, casefold, strip currency markers and brackets);
- try exact, then whole-token match (synonyms of 3 characters or fewer exact-only), then fuzzy with a threshold;
- assign one-to-one by score; leave unresolved ties unmapped with a 'column_mapping_ambiguous' warning;
- for multi-row headers, match the bottom row first, then the composed header.
In the profile: move 'langtext' to a separate long_description field. Split tender_quantity (lv-menge, ausschreibungsmenge, vertragsmenge) from quantity (menge, abrechnungsmenge, ar-menge), and give the line-total detector a config quantity_fields: [quantity, tender_quantity]. Drop or restrict to exact matching the synonyms 'price', 'preis', 'text', 'code', 'ref', 'type' and 'art'.

## 9. [medium] backend/app/models/profile.py RowClassificationRules (section_patterns, section_code_pattern), backend/app/normalization/builder.py contract, backend/tests/support/builders.py

**Problem:** The model now has section_level, section_path and closes_section_id, but the profile gives normalization nothing to compute them from:
- Keyword sections carry no level, so 'Los 1' and 'Titel 01' are the same level. 'Titel 01' then closes 'Los 1', and 'Summe Los 1' closes nothing.
- section_code_pattern stops at two levels and does not name its field.
- 'Summe Titel 01' cannot be linked to section '01'.
- AVA exports that print the Titel total on the heading row itself have no representation.
The test builder implements 'a subtotal closes the innermost open section and pops it', but the build_dataset contract does not state this rule. Detectors tested on builder data may therefore meet different semantics from the real normalizer. A table without sections that ends in 'Summe' or 'Total' (both now subtotal patterns) has no defined scope.

**Fix:** Add to the profile:
- section_levels: ordered pattern groups (1: los/bill, 2: titel/section, 3: untertitel/element);
- section_code_field, with level taken from the dotted segment count;
- a named group (?P<code>...) in subtotal patterns, so closes_section_id can be resolved by code.
Write the builder's stack rule, and 'no open section -> table scope', into the normalization contract. Flag heading rows that carry an amount (section_total_on_heading) so the subtotal detector reconciles them. Leave closes_section_id None when nothing establishes it.

## 10. [medium] backend/app/models/profile.py UnitDefinition.quantity_factor; boq.yaml unit pct; backend/app/models/values.py NumberValue.is_percent; backend/app/validation/contracts/decimal_math.py power_of_ten_factor

**Problem:** pct now has quantity_factor 0.01, which is correct for '5 | % | 5,000.00 | 250.00'. The contract does not say what happens when an operand is already a percentage. Excel percent-formatted cells are stored as 0.05 and parse with is_percent=True ('value is already /100'). Rows like '5% | % | 5,000 | 250' or '5,000 | % | 5% | 250' (UK 'Add for profit ... %') then recompute to 2.50 and are reported as confirmed violations. power_of_ten_factor returns k=2 and labels it a decimal-point or scaling error.

**Fix:** Document and test that quantity_factor applies only when neither the quantity nor the unit_price value has is_percent=True. Suppress power-of-ten hints for units whose quantity_factor is not 1 or whose dimension is ratio.

## 11. [medium] backend/app/profiles/boq.yaml item_code constraints.unique; backend/app/models/profile.py FieldConstraints.unique

**Problem:** Uniqueness is checked 'among item rows of one table'. UK SMM-style bills letter items A, B, C... and restart the letters on every page, with the page given in the footer or a separate column. Multi-Los LVs exported without the Los prefix restart OZ numbering in each Los. Table-wide uniqueness reports most of these items as duplicate codes (confirmed constraint violations).

**Fix:** Add a generic unique_scope: table | section | top_section and use section scope in boq.yaml. Treat codes that repeat across carry-forward or page breaks as abstain, or use a composite key with a page or Los column when one is mapped.

## 12. [medium] backend/app/profiles/boq.yaml detector_defaults.deterministic.unit_compatibility.description_rules

**Problem:** hourly_work_in_time_units allows only [time], but Stundenlohn and daywork blocks contain non-hour items, which get flagged: 'Zuschlag auf Stoffkosten für Stundenlohnarbeiten | %', 'Stoffe für Stundenlohnarbeiten | psch', 'Provisional sum for daywork labour | Item', 'Daywork materials: percentage addition | %'. The site-setup rule is now anchored, but it still fires on Kurztexte that begin with the Titel word ('Baustelleneinrichtung, Bauzaun aufstellen und vorhalten | m', 'Baustelleneinrichtung, Container | St') and on piling items ('Mobilisation of rig to each pile position | Nr'). The brief allows contextual unit rules only when the category is established.

**Fix:** Allow [time, lump_sum, ratio] for daywork. Add an exclude_pattern field to description rules (zuschlag|stoffe?|material|gerät|plant|percentage|provisional). Restrict site setup to descriptions that are only the phrase, for example '^\s*baustelleneinrichtung\s*(einrichten|vorhalten|räumen|komplett)?\s*$', and drop mobilisation or allow count for it. Emit these as semantic_warning, not as confirmed violations.

## 13. [medium] backend/app/profiles/boq.yaml units; backend/app/profiles/units.py unit_key

**Problem:** These units do not resolve (verified):
- UK/international: 'Item', 'Sum', 'L/S', 'Lot', 'Job', 'Prov Sum', 'PC Sum', 'Nos', "No's", 'Pair', 'pr', 'MT', 'Rmt', 'R.M.';
- German: 'Pschl.', 'Tg', 'AT';
- rental and transport compounds: 'm²Wo', 'm2 x Wo', 'St.Wo', 'Stck/Wo', 'm²·cm', 'm3km', 'tkm'.
Prelims bills ('Item') and Indian or Middle-East BoQs ('Nos') would get a unit finding on most rows, and unit compatibility cannot judge them. Multiplier units such as '100 St' or '1000 kg' are unknown, so a line-total detector using factor 1 would report a x100 scaling error.

**Fix:** Add aliases: ls gets item, sum, l/s, lot, job, ps, prov sum, provisional sum and pc sum (not 'pc', which already means piece); pcs gets nos and no's; t gets mt; m gets rm, rmt and running metre; d gets tg, at and kt; add a pair unit. Add compound units with their own dimensions (area_time, count_time, transport). Make unit_key fold '·', '×', '*' and spacing around 'x' or '/'. The line-total detector should abstain, or use a declared factor, for units with a leading numeric multiplier.

## 14. [medium] backend/app/models/dataset.py Row (no link from TEXT continuation rows to their item) and RowKind.TEXT

**Problem:** Print-style LV exports put OZ and Kurztext on the first row, the Langtext lines below it, and Menge/ME/EP/GP on the last line. Row-level classification then yields a TEXT row that holds the OZ and an ITEM without an item_code. Consequences:
- a missing-code violation on the ITEM;
- 'wie Pos. 01.02.0030' is reported as an invalid reference, because the code is not on an ITEM;
- duplicate keys break;
- markers in the Langtext ('Bedarfsposition ohne GB') are invisible to the totals rules.
Even when values are on the first row, detectors cannot read the item's full text.

**Fix:** Add Row.belongs_to_row_id (continuation row -> owning item), set by normalization, and a profile option item_block_values_row: first | last | detect. Add ValidationContext.item_text() for the combined text. The required-values, reference and duplicate detectors should use the owning item's code, and totals rules may search the continuation text.

## 15. [medium] backend/app/ingestion/base.py RawSheet (only sheet-level hidden); backend/app/models/dataset.py Row; backend/app/normalization/builder.py ('non-hidden sheet')

**Problem:** openpyxl 3.1.5 exposes each row's hidden flag and outlineLevel, but the raw layer has nowhere to store them. Priced BoQs often hide withdrawn items or helper rows. If the document totals with SUBTOTAL(109,...), it excludes them while the detector includes them, which produces a false positive. If it totals with SUM, they are silently part of the total and the reviewer cannot be told. AVA exports encode Titel/Untertitel as Excel outline groups, the most reliable domain-neutral hierarchy signal, and that signal is lost. Hidden sheets are skipped with no warning stated in the contract.

**Fix:** Add RawSheet.hidden_rows, hidden_columns and row_outline_levels, plus Row.source_hidden and outline_level. Normalization keeps hidden rows, warns 'hidden_rows_present' (needs_review) and may derive section_level from outline levels. Skipped hidden sheets are listed in an extraction warning.

## 16. [medium] backend/app/models/schema.py TableDecisions

**Problem:** Reviewers can override header rows, column fields, row kinds and not-data rows. They cannot override the facts the BoQ heuristics will most often get wrong: whether an item counts toward totals ('mit/ohne GB', optional items), a section's level or parent, which section a subtotal closes, or a confirmed unit. Brief Part I requires 'identify section hierarchy ... confirm units'. A wrong totals flag therefore cannot be corrected: the subtotal stays a recurring false positive and that section is never really checked.

**Fix:** Add fields keyed by source row: counts_toward_totals: dict[int, bool | None], section_levels: dict[int, int], closes_section: dict[int, int | None] (subtotal row -> section row) and units: dict[int, str] (or column-level unit aliases). Apply them in build_dataset the same way as row_kinds.

## 17. [low] backend/app/profiles/boq.yaml quantity and unit_price constraints (minimum: "0")

**Problem:** Credit positions are legitimate negatives. Demolition LVs price scrap as a credit ('Vergütung für Altmetall, Gutschrift | t | -120,00'), UK BoQs carry 'Credit for salvaged materials', and variation BoQs list omissions with negative quantities. All of these become confirmed constraint violations.

**Fix:** Drop the minimum on unit_price (and quantity) in the BoQ profile. Alternatively add a generic exempt_label_patterns to FieldConstraints (gutschrift|vergütung|credit|omit|deduct|minder) and report other negatives as low-severity warnings.

## 18. [low] docs/api/rest-api.md (Datasets/rows) and docs/architecture/data-model.md (entity diagram)

**Problem:** Both docs still describe the old row shape: header_row_number, a flat section_row_id, user_edited, and classification with only {kind, rule, matched_text}. The current model has header_row_numbers, section_path, closes_section_id, section_level, counts_toward_totals and totals_rule. API and frontend engineers working from the docs will omit totals participation and hierarchy from row rendering and from row_kind_counts.

**Fix:** Update both docs to the current Row, RowClassification and HeaderDetection shape, and state the decision table and closing semantics once in data-model.md.
