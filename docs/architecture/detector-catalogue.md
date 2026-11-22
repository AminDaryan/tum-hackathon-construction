# Detector catalogue

Generated from the detectors' specs (`backend/app/validation/catalogue_markdown.py`); do not edit by hand. Every detector is deterministic, runs locally and uses no paid service. Every validation runs every detector (ADR 0010); a detector that does not apply to a dataset reports why.
Parameters show their code defaults; a profile's `detector_defaults` may set any of them, an LLM plan only those marked *plan or profile*. `GET /api/v1/detectors?profile_id=<id>` returns the values a profile gives them (`profile_config`).
The finding category of a finding (`finding_category`) is its detector's, or its rule's where the two differ (`backend/app/models/finding_category.py`); none means that the finding is about reading the file ("Reading the file"). The evidence class does not change it: a finding the evidence policy downgraded to `extraction_uncertainty` keeps its category.

| Detector | Category | Finding category | Cost |
| --- | --- | --- | --- |
| [Currency consistency](#deterministiccurrency_consistency) | `deterministic` | `inconsistency` | low |
| [Invalid data types](#deterministicdata_type_conformance) | `deterministic` | `error` | low |
| [Exact duplicate rows](#deterministicexact_duplicates) | `deterministic` | `inconsistency` | low |
| [Extraction uncertainty](#deterministicextraction_quality) | `deterministic` | none (reading the file) | low |
| [Domain constraints](#deterministicfield_constraints) | `deterministic` | `error` | low |
| [Spreadsheet formula errors and missing formula results](#deterministicformula_errors) | `deterministic` | `error` | low |
| [Grand total, tax and gross reconciliation](#deterministicgrand_total) | `deterministic` | `error` | low |
| [Numbering hierarchy](#deterministichierarchy) | `deterministic` | `error` | low |
| [Line total = quantity × unit price](#deterministicline_total) | `deterministic` | `error` | low |
| [Invalid numerical values](#deterministicnumeric_validity) | `deterministic` | `error` | low |
| [Reference integrity](#deterministicreference_integrity) | `deterministic` | `ambiguity` | low |
| [Missing required values](#deterministicrequired_values) | `deterministic` | `error` | low |
| [Subtotal reconciliation](#deterministicsubtotal) | `deterministic` | `error` | low |
| [Unit compatibility](#deterministicunit_compatibility) | `deterministic` | `error` | low |
| [Unit price components add up to the unit price](#deterministicunit_price_components) | `deterministic` | `error` | low |
| [Unit vocabulary](#deterministicunit_vocabulary) | `deterministic` | none (reading the file) | low |
| [Bid prices (positions not offered, zero, token and negative prices, hourly rates)](#domainboq_bid_prices) | `domain` | `error` | low |
| [Bill clauses (risk, assumptions, vague wording, references)](#domainboq_clauses) | `domain` | `risk` | low |
| [Companion work (BoQ)](#domainboq_companion_work) | `domain` | `omission` | low |
| [Contradictions within an item](#domainboq_contradictions) | `semantic` | `ambiguity` | low |
| [Unclear or incomplete descriptions](#domainboq_description_clarity) | `semantic` | `ambiguity` | low |
| [Missing items in the numbering](#domainboq_numbering) | `statistical` | `omission` | low |
| [Contingency positions and hourly work](#domainboq_position_types) | `domain` | `risk` | low |
| [Required attributes (BoQ)](#domainboq_required_attributes) | `domain` | `ambiguity` | low |
| [Paid separately, without a paying position (BoQ)](#domainboq_separate_payment) | `domain` | `omission` | low |
| [Bid against its tender](#domainboq_tender_comparison) | `domain` | `inconsistency` | low |
| [Typing slips in texts](#domainboq_typos) | `semantic` | `error` | low |
| [Bill against model quantities (IFC)](#domainmodel_quantities) | `domain` | `inconsistency` | low |
| [Standard text keys (STLB-Bau)](#domainstandard_text_keys) | `domain` | `inconsistency` | low |
| [Claude bill review](#llmbill_review) | `semantic` | `risk` | low |
| [Nearly identical positions in one section](#machine_learningnear_duplicates) | `machine_learning` | `inconsistency` | medium |
| [Position closer to another section](#semanticsection_fit) | `semantic` | `inconsistency` | medium |
| [Unit unlike similar positions](#semanticunit_fit) | `semantic` | `inconsistency` | medium |
| [Historical unit price and quantity (real offers)](#statisticalhistorical_price) | `statistical` | `risk` | low |
| [Unit price below a published material value](#statisticalopen_price_reference) | `statistical` | `risk` | low |
| [Unit price far from comparable positions](#statisticalpeer_price) | `statistical` | `risk` | medium |
| [Quantity a power of ten off identical positions](#statisticalquantity_factor) | `statistical` | `inconsistency` | low |
| [Identical positions with different unit prices](#statisticalrate_consistency) | `statistical` | `inconsistency` | low |

## deterministic.currency_consistency

**Currency consistency** (version 1.0.0). Finds explicit currency markers that disagree within a row, differ from the expected currency, or stand out from the rest of a table.

- Applies when: Tables with mapped monetary fields and at least one explicit currency.
- Required fields: none; optional: none
- Evidence classes: `confirmed_rule_violation`, `needs_external_context`
- Issue categories: `currency`
- Finding category: `inconsistency`
- Limitations:
  - Only explicit markers are compared; amounts without a currency marker are never assumed to be in a default currency.
  - Ambiguous symbols such as '$' are not resolved to a currency.
- Parameters:
  - `fields` (plan or profile): `null`. Monetary fields to check; None: every mapped field with role monetary.
  - `currency_field` (plan or profile): `null`. Field holding each row's currency; None: the field with role currency.
  - `severity` (plan or profile): `medium`. Severity of the findings.
  - `max_cells_per_issue` (plan or profile): `50`. The most cells a grouped finding lists.
  - `expected_currency` (profile): `null`. ISO 4217 code every explicit marker should carry (None: not checked).

## deterministic.data_type_conformance

**Invalid data types** (version 1.0.0). Reports values that could not be read as their field's type (text in a quantity, an unreadable date), values with several possible readings (decimal separator, day/month order), values of the wrong type, and unusual minority types in unmapped columns.

- Applies when: Every dataset; mapped fields need a number, date or yes/no type.
- Required fields: none; optional: none
- Evidence classes: `confirmed_rule_violation`, `extraction_uncertainty`, `suspected_anomaly`
- Issue categories: `data_type`
- Finding category: `error`; rule `ambiguous_value`: none (reading the file)
- Limitations:
  - Only item and total rows are checked in mapped columns; headings and notes may hold any text.
  - Minority types in unmapped columns are observations, not errors; no score is attached to them.
- Parameters:
  - `fields` (plan or profile): `null`. Fields to check; None = every mapped number, date or yes/no field.
  - `max_cells_per_issue` (plan or profile): `50`. Cells of one column and problem reported one by one; more are grouped.
  - `check_unmapped_columns` (profile): `true`. Look for minority types in unmapped columns.
  - `dominance_threshold` (profile): `0.95`. Share of the dominant type in a column.
  - `min_non_empty` (profile): `10`. Values a column needs before minorities are reported.
  - `severity_invalid_value` (profile): `medium`. Severity of values not readable as their type.
  - `severity_wrong_type` (profile): `medium`. Severity of values of another type.
  - `severity_ambiguous_value` (profile): `medium`. Severity of values with several readings.
  - `severity_minority_type` (profile): `low`. Severity of minority types in unmapped columns.

## deterministic.exact_duplicates

**Exact duplicate rows** (version 1.1.0). Finds item rows that repeat another item row of the same table (or of the same section, where the profile says so) in every compared column, and the amount they may count twice.

- Applies when: Every table with item rows.
- Required fields: none; optional: none
- Evidence classes: `confirmed_rule_violation`
- Issue categories: `duplicate`
- Finding category: `inconsistency`
- Limitations:
  - Only exact repeats are found: a different item code, description or amount makes rows distinct.
  - The double count is an amount at risk, not a confirmed error: some documents repeat an item on purpose.
  - With the section scope, a row repeated in another section is not a duplicate.
- Parameters:
  - `ignore_fields` (plan or profile): `[]`. Fields whose columns are not compared.
  - `ignore_columns` (plan or profile): `[]`. Column headers that are not compared (case-insensitive).
  - `case_sensitive` (profile): `false`. Compare text by exact case.
  - `severity_exact_duplicate` (profile): `medium`. Severity of a group of identical rows.
  - `min_non_empty_cells` (profile): `2`. Rows with fewer non-empty compared cells are not compared.
  - `max_cells_per_issue` (plan or profile): `50`. The most cells a finding highlights.
  - `total_field` (plan or profile): `line_total`. Monetary field summed for the potential double count.
  - `scope` (profile): `table`. Compare the item rows of a whole table, or of one section at a time.
  - `required_fields` (profile): `[]`. Rows with an empty cell in one of these fields are not compared; tables that do not map one of them are not compared.
  - `relative_wording_pattern` (profile): `null`. Wording that refers to the row before ('as before'): such a row is compared together with the row it refers to.
  - `relative_wording_fields` (profile): `["description"]`. Fields searched for the relative wording.

## deterministic.extraction_quality

**Extraction uncertainty** (version 1.0.0). Reports what the extraction could not establish reliably: values read with low OCR confidence, unrecognized headers, uncertain or missing column mappings and other structure warnings.

- Applies when: Every dataset.
- Required fields: none; optional: none
- Evidence classes: `extraction_uncertainty`
- Issue categories: `extraction`
- Finding category: none (reading the file)
- Limitations:
  - Confidence is reported only where the extraction engine scores values (OCR/PDF); spreadsheet and CSV values are read verbatim.
  - A header similarity is a similarity of spelling, not a probability that the mapping is right.
- Parameters:
  - `fields` (plan or profile): `null`. Fields whose cells are checked for low confidence; None = every mapped field.
  - `max_issues_per_column` (plan or profile): `200`. Low-confidence cells of one column and confidence band beyond which they form one finding.
  - `report_header_uncertainty` (profile): `true`. Report headers found by layout, first row or not at all.
  - `report_fuzzy_mappings` (profile): `true`. Report columns mapped by approximate header spelling.
  - `report_unmapped_fields` (profile): `true`. Report required profile fields without a column.
  - `report_extraction_warnings` (profile): `true`. Report the other normalization warnings that need review.
  - `severity_low_confidence` (profile): `low`. Severity of values scored below the threshold.
  - `severity_very_low_confidence` (profile): `medium`. Severity of values scored below half the threshold.
  - `severity_no_mapped_columns` (profile): `medium`. Severity of tables without a mapped column.
  - `severity_header_uncertain` (profile): `medium`. Severity of headers found by layout or not at all.
  - `severity_required_field_unmapped` (profile): `medium`. Severity of required fields without a column.
  - `severity_fuzzy_mapping` (profile): `low`. Severity of columns mapped by approximate spelling.
  - `severity_extraction_warning` (profile): `medium`. Severity of other normalization warnings.

## deterministic.field_constraints

**Domain constraints** (version 1.0.0). Checks item rows against the patterns, allowed values and uniqueness rules the profile sets for their fields, such as unique item codes.

- Applies when: Tables mapping a field with a pattern, allowed values or a uniqueness rule.
- Required fields: none; optional: none
- Evidence classes: `confirmed_rule_violation`
- Issue categories: `constraint`
- Finding category: `error`
- Limitations:
  - A value longer than 500 characters never matches a pattern.
  - Identifiers are compared ignoring case, spaces and trailing dots, but not leading zeros: '01.10' and '1.10' are different codes here.
- Parameters:
  - `fields` (plan or profile): `null`. Fields to check; None = every field with a pattern, allowed values or a uniqueness rule.
  - `constraints` (profile): `{}`. Constraints per field id, replacing the profile's for that field.
  - `max_cells_per_issue` (plan or profile): `50`. Pattern or allowed-value failures of one field beyond which they form one finding; also the most cells a finding highlights.
  - `case_sensitive_unique` (profile): `false`. Compare values of non-identifier fields for uniqueness by exact text.
  - `severity_pattern` (profile): `low`. Severity of values that do not match the pattern.
  - `severity_allowed_values` (profile): `medium`. Severity of values not among the allowed ones.
  - `severity_unique` (profile): `medium`. Severity of repeated values of a unique field.

## deterministic.formula_errors

**Spreadsheet formula errors and missing formula results** (version 1.0.0). Reports cells whose stored value is a spreadsheet error (#REF!, #DIV/0!, #N/A, ...) as confirmed rule violations, formula cells whose result the file does not store as extraction uncertainty, and values computed from another workbook as needing external context. Inspects every cell of every table, mapped or not; formulas are never evaluated.

- Applies when: Every dataset. Findings need formulas or error values, so delimited text (CSV) sources normally produce none.
- Required fields: none; optional: none
- Evidence classes: `confirmed_rule_violation`, `extraction_uncertainty`, `needs_external_context`
- Issue categories: `formula_error`
- Finding category: `error`; rule `formula_result_unavailable`: none (reading the file)
- Limitations:
  - Formulas are never evaluated: a formula without a stored result is reported as unavailable, never recomputed.
  - Links to other workbooks are recognised from the formula syntax ([n] or [Book.xlsx] prefixes and quoted paths before '!'); links hidden in defined names or in text passed to INDIRECT are not detected.
  - Formula text longer than 8,192 characters (Excel's limit) is not scanned for links; such formulas are counted in the coverage.
  - Rows a reviewer excluded are not inspected.
- Parameters:
  - `flag_external_references` (profile): `true`. Report values whose formula refers to another workbook (profile switch).
  - `severity` (plan or profile): `high`. Severity of spreadsheet error values (formula_error).
  - `severity_formula_result_unavailable` (profile): `medium`. Severity of formulas without a stored result (profile).
  - `severity_external_reference` (profile): `low`. Severity of links to other workbooks (profile).
  - `max_cells_per_issue` (plan or profile): `50`. Cells of one column and error code reported one by one; more are grouped into one finding that highlights this many cells.

## deterministic.grand_total

**Grand total, tax and gross reconciliation** (version 1.0.0). Checks each grand total against the sum of what it covers, each tax line against its rate times the net, and each gross total against net plus tax, under every admissible reading.

- Applies when: Tables with grand total, tax or gross total rows and a mapped amount field.
- Required fields: none; optional: none
- Evidence classes: `confirmed_rule_violation`, `needs_external_context`, `extraction_uncertainty`
- Issue categories: `grand_total`
- Finding category: `error`; rule `grand_total_display_rounding`: none (reading the file); rule `grand_total_scope_ambiguous`: none (reading the file); rule `gross_total_display_rounding`: none (reading the file); rule `gross_total_scope_ambiguous`: none (reading the file)
- Limitations:
  - Members are summed by their stated amounts; a wrong line or subtotal is reported once, by its own check.
  - A tax rate is read only from the tax line's text; a tax line without a stated rate, or one of several tax lines of one net with different rates, is not checked.
  - A total whose scope cannot be established, or whose members cannot all be read, is not checked (it is counted and noted).
- Parameters:
  - `total_field` (plan or profile): `line_total`. Field holding the amounts.
  - `severity` (plan or profile): `high`. Severity of a confirmed mismatch.
  - `max_reference_cells` (plan or profile): `50`. The most summed cells a finding lists.
  - `rounding` (profile): `{"decimal_places": 2, "mode": "half_up"}`. How a sum is rounded before comparison.
  - `tolerance` (profile): `{"absolute": "0.01", "relative": "0", "per_term_absolute": "0"}`. Allowed difference.
  - `display_rounding_drift_per_term` (profile): `0.005`. Per printed value, for delimited-text tables only.
  - `check_tax_lines` (profile): `true`. Check tax lines: rate × net.
  - `tax_rate_pattern` (profile): `(\d{1,3}(?:[.,]\d{1,4})?)\s*%`. Finds the rate in a tax line's text; its one capture group is the percent.
  - `tax_rounding` (profile): `{"decimal_places": 2, "mode": "half_up"}`. How rate × net is rounded.
  - `check_gross_totals` (profile): `true`. Check gross totals: net + adjustments + tax lines.
  - `severity_undecided` (profile): `medium`. Severity of totals that depend on undecided items.
  - `severity_ambiguous_structure` (profile): `medium`. Severity of totals matching none of several possible scopes.
  - `severity_display_rounding` (profile): `info`. Severity of differences explained by printed rounding.

## deterministic.hierarchy

**Numbering hierarchy** (version 1.0.0). Finds codes that contradict the document's own numbering: an item code that does not start with the code of its section, a section code that does not start with the code of the section it is in, and an item code lower than the one before it.

- Applies when: Tables that map the item code and have at least one section with a code.
- Required fields: `item_code`; optional: none
- Evidence classes: `confirmed_rule_violation`
- Issue categories: `numbering`
- Finding category: `error`
- Limitations:
  - Only the numbering is compared: whether an item belongs in its section by its content is not checked.
  - Codes with letters are compared by their prefix only, not by their order; a code with numbers where its section has letters (or the reverse) is not compared.
  - A code typed as a number with decimals may have lost trailing zeros (1.10 reads 1.1): it is not ordered, and such a section is not used as a prefix.
  - Sections without a code, and everything inside them, are not compared.
- Parameters:
  - `code_field` (plan or profile): `item_code`. Field that holds the item codes.
  - `max_row_issues` (plan or profile): `20`. Findings of one rule and table reported one by one; more are grouped.
  - `severity_item_outside_section` (profile): `medium`. Severity of an item code outside its section.
  - `severity_section_outside_parent` (profile): `medium`. Severity of a section code outside the section it is in.
  - `severity_code_order` (profile): `low`. Severity of an item code lower than the code of the item before it.

## deterministic.line_total

**Line total = quantity × unit price** (version 1.2.0). Recomputes each item's line total from its quantity and unit price (with the unit's factor, e.g. 0.01 for percent) and compares it with the stated total. An item discount that the file declares (GAEB) is taken off by the GAEB rounding rule. Where the profile says the unit price prevails (VOB/A § 16c), a mismatch states the corrected line total; a lump sum keeps its stated amount.

- Applies when: Tables that map the quantity, unit price and line total fields.
- Required fields: none; optional: none
- Evidence classes: `confirmed_rule_violation`
- Issue categories: `arithmetic`
- Finding category: `error`
- Limitations:
  - A mismatch shows that quantity, unit price and total disagree, not which one is wrong.
  - Rows with a unit multiplier such as '100 St' are not checked.
- Parameters:
  - `quantity_field` (plan or profile): `quantity`. Field holding the quantity.
  - `price_field` (plan or profile): `unit_price`. Field holding the unit price.
  - `total_field` (plan or profile): `line_total`. Field holding the line total.
  - `unit_field` (plan or profile): `unit`. Field holding the unit.
  - `discount_field` (plan or profile): `discount_percent`. Field holding an item discount in percent; used only where it is mapped.
  - `severity` (plan or profile): `high`. Severity of a mismatch.
  - `rounding` (profile): `{"decimal_places": 2, "mode": "half_up"}`. How the recomputation is rounded.
  - `tolerance` (profile): `{"absolute": "0.01", "relative": "0", "per_term_absolute": "0"}`. Allowed difference.
  - `infer_precision_from_column` (profile): `true`. Round to the decimal places the table's line totals are written with.
  - `skip_unit_dimensions` (profile): `[]`. Unit dimensions whose rows are not checked.
  - `detect_scaling_errors` (profile): `true`. Note when a total is about a power of ten off.
  - `prevailing_value` (profile): `none`. What prevails in a mismatch: none (the finding does not say which value is wrong) or unit_price (the line total is corrected to quantity × unit price).
  - `prevailing_rule` (profile): `null`. The rule the finding cites when the unit price prevails.
  - `lump_sums` (profile): `{"unit_dimensions": [], "text_field": null, "text_pattern": null, "rule": "", "undetermined_warnings": [], "undetermined_note": ""}`. Lump-sum positions, whose stated amount prevails instead.

## deterministic.numeric_validity

**Invalid numerical values** (version 1.0.0). Checks numbers of item rows against the bounds, whole-number, decimal-place and zero rules the profile (or the configuration) sets for their field.

- Applies when: Tables that map a number field with constraints.
- Required fields: none; optional: none
- Evidence classes: `confirmed_rule_violation`
- Issue categories: `numeric_value`
- Finding category: `error`
- Limitations:
  - Only usable numbers are checked; empty, marker and unreadable cells are skipped and counted.
  - Decimal places are counted on the normalized value (12.50 has one).
- Parameters:
  - `fields` (plan or profile): `null`. Fields to check; None = every number field with constraints.
  - `constraints` (profile): `{}`. Constraints per field id, replacing the profile's for that field.
  - `severity_minimum` (profile): `medium`. Severity of values below the minimum.
  - `severity_maximum` (profile): `medium`. Severity of values above the maximum.
  - `severity_integer_only` (profile): `low`. Severity of fractions in whole-number fields.
  - `severity_max_decimal_places` (profile): `low`. Severity of too many decimal places.
  - `severity_zero` (profile): `low`. Severity of zero where it is not allowed.

## deterministic.reference_integrity

**Reference integrity** (version 1.0.0). Checks that references to identifiers resolve within the document: values of reference fields must name an existing identifier (confirmed rule violation when not), and references written in text (found by profile patterns, e.g. 'wie Pos. 01.02.0030') that name no identifier of the document need external context (the position may be in another document or lot). Codes are compared by segments, so leading zeros do not matter.

- Applies when: At least one configured rule whose source (or text) field and target field are mapped in some table.
- Required fields: none; optional: none
- Evidence classes: `confirmed_rule_violation`, `needs_external_context`, `extraction_uncertainty`
- Issue categories: `reference`
- Finding category: `ambiguity`
- Limitations:
  - References in text are found only where the profile's patterns match, and only in the first 500 characters of a text; other wording is not recognised.
  - A reference to another document or lot cannot be resolved from this document.
  - Identifiers are compared by code segments only (separators '.' and '/', leading zeros ignored); differently structured codes for the same item do not match.
  - At most 50 references per reference cell are checked.
- Parameters:
  - `text_references` (profile): `[]`. References found in text by patterns (profile-controlled).
  - `rules` (profile): `[]`. Fields whose values are references (profile-controlled).
  - `severity_field_rule` (plan or profile): `medium`. Severity of unresolved references in reference fields.
  - `severity_text_rule` (plan or profile): `low`. Severity of unresolved references written in text.

## deterministic.required_values

**Missing required values** (version 1.3.0). Reports empty cells in fields the profile requires (for example the quantity, unit, unit price and total of an item), with profile exemptions for lump sums, for items that are not counted in totals and for marked item types.

- Applies when: Datasets whose profile marks fields as required (or a plan that names fields); each field is checked in the tables that map it.
- Required fields: none; optional: none
- Evidence classes: `confirmed_rule_violation`
- Issue categories: `missing_value`
- Finding category: `error`
- Limitations:
  - Only cells that are truly empty are reported; value markers such as 'Incl.' or 'psch' count as values.
  - A required column that is empty in every checked row (an unpriced bill) is noted once, not reported row by row (only_populated_columns).
  - Required fields without a mapped column are reported by the extraction quality check, not here.
- Parameters:
  - `fields` (plan or profile): `null`. Fields to check; None = every profile field marked required.
  - `severity_by_field` (plan or profile): `{}`. Severity per field; default high for quantities and amounts, else medium.
  - `max_row_issues_per_field` (plan or profile): `50`. Missing cells of one field and table reported one by one; more are grouped.
  - `only_populated_columns` (profile): `true`. Skip a required column that is empty in every checked row of a table (an unpriced bill), with one note instead of one finding per row.
  - `exemptions` (profile): `[]`. Rows exempt from the requirement (profile rules).

## deterministic.subtotal

**Subtotal reconciliation** (version 1.0.0). Checks each subtotal against the sum of the amounts it covers, under every admissible reading of the section structure and of undecided items.

- Applies when: Tables with subtotal rows and a mapped amount field.
- Required fields: none; optional: none
- Evidence classes: `confirmed_rule_violation`, `needs_external_context`, `extraction_uncertainty`
- Issue categories: `subtotal`
- Finding category: `error`; rule `subtotal_display_rounding`: none (reading the file); rule `subtotal_scope_ambiguous`: none (reading the file)
- Limitations:
  - Members are summed by their stated amounts; a wrong line is reported once, by the line total check.
  - A subtotal whose scope cannot be established, or whose members cannot all be read, is not checked (it is counted and noted).
- Parameters:
  - `total_field` (plan or profile): `line_total`. Field holding the amounts.
  - `severity` (plan or profile): `high`. Severity of a confirmed mismatch.
  - `max_reference_cells` (plan or profile): `50`. The most summed cells a finding lists.
  - `rounding` (profile): `{"decimal_places": 2, "mode": "half_up"}`. How a sum is rounded before comparison.
  - `tolerance` (profile): `{"absolute": "0.01", "relative": "0", "per_term_absolute": "0"}`. Allowed difference.
  - `display_rounding_drift_per_term` (profile): `0.005`. Per printed value, for delimited-text tables only.
  - `severity_undecided` (profile): `medium`. Severity of totals that depend on undecided items.
  - `severity_ambiguous_structure` (profile): `medium`. Severity of totals matching none of several possible scopes.
  - `severity_display_rounding` (profile): `info`. Severity of differences explained by printed rounding.

## deterministic.unit_compatibility

**Unit compatibility** (version 1.0.0). Advisory warnings about units: descriptions whose wording the profile associates with other unit dimensions (for example hourly work measured in m³), fractional quantities in whole-number units, lump sums with a quantity other than 1, and identical descriptions measured in units of different dimensions. Findings are semantic warnings, never confirmed violations.

- Applies when: The profile defines units, the unit field is mapped, and the description or quantity field needed by an enabled check is mapped in the same table.
- Required fields: `unit`; optional: `description`, `quantity`
- Evidence classes: `semantic_warning`
- Issue categories: `unit`
- Finding category: `error`; rule `same_description_dimension`: `inconsistency`
- Limitations:
  - Advisory: description rules infer the kind of work from wording, which can be wrong; the findings are warnings for a reviewer, not errors.
  - Only the first 500 characters of a description are matched against rules.
  - Identical descriptions are compared after Unicode normalization, case folding and whitespace collapsing only; near-identical wording is not grouped.
  - Rows with empty or unknown units are ignored.
- Parameters:
  - `description_rules` (profile): `[]`. Description wording -> allowed unit dimensions (profile).
  - `check_integer_quantities` (profile): `true`. Warn about fractional quantities in whole-number units.
  - `check_lump_sum_quantity` (profile): `true`. Warn about lump sums with a quantity other than 1.
  - `check_same_description_dimension` (profile): `true`. Warn when identical descriptions use units of different dimensions.
  - `min_description_words` (profile): `3`. Words a description needs to be compared.
  - `same_description_exclude_pattern` (profile): `null`. Descriptions matching this pattern are not compared with each other: relative wording ('wie vor, jedoch ...', 'as before but ...') repeats verbatim for different work (profile-controlled).
  - `description_field` (plan or profile): `description`
  - `quantity_field` (plan or profile): `quantity`
  - `unit_field` (plan or profile): `unit`
  - `max_cells_per_issue` (plan or profile): `50`. Cells highlighted per description group.
  - `severity_same_description_dimension` (profile): `medium`. Severity of identical descriptions in units of different dimensions.
  - `severity_fractional_count` (profile): `low`. Severity of fractions in whole-number units.
  - `severity_lump_sum_quantity` (profile): `low`. Severity of lump sums with a quantity other than 1.

## deterministic.unit_price_components

**Unit price components add up to the unit price** (version 1.0.0). Adds up each item's unit price components (GAEB Preisanteile, up to six, for example wages, materials, plant and other costs) and compares the sum, rounded to the unit price's decimal places, with the unit price.

- Applies when: Tables that map the unit price and at least one unit price component (a reviewer maps the components; no header does), and GAEB tables whose file holds components the import does not read yet (the check then says so).
- Required fields: `unit_price`; optional: `unit_price_component_1`, `unit_price_component_2`, `unit_price_component_3`, `unit_price_component_4`, `unit_price_component_5`, `unit_price_component_6`
- Evidence classes: `confirmed_rule_violation`
- Issue categories: `arithmetic`
- Finding category: `error`
- Limitations:
  - The GAEB import does not read the unit price components yet (UPComp1 to UPComp6 in GAEB XML, record 30 in GAEB 90): in a GAEB file the components are not checked, and the run says so.
  - A mismatch shows that the components and the unit price disagree, not which component is wrong.
- References: GAEB DA XML 3.3, Fachdokumentation 2023-01, 4.6.5 Aufgliederung von Einheitspreisen
- Parameters:
  - `price_field` (plan or profile): `unit_price`. Field holding the unit price.
  - `component_fields` (plan or profile): `["unit_price_component_1", "unit_price_component_2", "unit_price_component_3", "unit_price_component_4", "unit_price_component_5", "unit_price_component_6"]`. Fields holding the unit price components (GAEB allows up to six).
  - `severity` (plan or profile): `medium`. Severity of a mismatch.
  - `rounding_mode` (profile): `half_up`. How the sum is rounded to the unit price's decimal places.
  - `not_imported_warning` (profile): `null`. Extraction warning code whose message counts elements the import kept in the file but did not read.
  - `not_imported_elements` (profile): `[]`. Element names in that warning that are unit price components.

## deterministic.unit_vocabulary

**Unit vocabulary** (version 1.0.0). Reports units of item rows that the profile's unit vocabulary does not know (after aliases, leading multipliers such as '100 St' and reviewer unit aliases), one finding per distinct unknown unit and table. Such rows cannot take part in unit-dependent checks until the unit is corrected or confirmed as an alias.

- Applies when: The unit field is mapped and the profile defines a unit vocabulary.
- Required fields: `unit`; optional: none
- Evidence classes: `needs_external_context`
- Issue categories: `unit`
- Finding category: none (reading the file)
- Limitations:
  - Only the profile's vocabulary, leading multipliers and reviewer aliases are known: a correct unit missing from the profile is reported until it is added or aliased.
  - Units are grouped by their normalized spelling; different spellings of one unknown unit that normalize differently are reported separately.
- Parameters:
  - `unit_field` (plan or profile): `unit`. Field holding the unit of item rows.
  - `severity` (plan or profile): `low`. Severity of unknown units.
  - `max_cells_per_issue` (plan or profile): `200`. Cells highlighted per unknown unit.

## domain.boq_bid_prices

**Bid prices (positions not offered, zero, token and negative prices, hourly rates)** (version 1.4.0). Checks the unit prices of a priced bill or bid before submission: positions marked 'nicht angeboten', unit prices of 0,00 on a position with a quantity, token prices (such as 0,01) that suggest costs moved into other positions, and hourly labour rates below the statutory minimum wage; also item discounts exceeding 100%, unit prices below zero, and unit prices that carry value added tax.

- Applies when: Tables with a unit price, or a position marked not offered, on at least one item row (a priced bill or bid).
- Required fields: `unit_price`; optional: `item_type`, `item_code`, `unit`, `description`, `long_description`, `discount_percent`
- Evidence classes: `suspected_anomaly`, `confirmed_rule_violation`
- Issue categories: `price`, `completeness`
- Finding category: `error`; rule `price_below_floor`: `risk`
- Limitations:
  - The hourly floor is the German statutory minimum wage of the date in its description; a collective agreement for the trade may set a higher wage.
  - Hourly labour is recognised by an hour unit with the item type Stundenlohnarbeiten or a text that names labour; other low prices are left to the comparison checks.
  - A table whose unit price is empty on every item row (a tender) is not checked.
  - In a GAEB X84 or D84 bid, whether a position counts toward the total is stated in the tender it answers, not in the bid.
  - A negative price is not reported when the position's text calls it a credit or deduction; whether that credit is intended is not checked.
  - Value added tax in a unit price shows only while the price is not rounded to cents; a gross price rounded to cents looks like a net price.
- References: GAEB DA XML 3.3, §4.6.4 (missing price, not offered, 0,00) and §4.5.2 (the base and every alternative execution are offered); BGH, decision of 18 May 2004, X ZB 7/04 (no costs moved into other positions); VOB/A 2019 § 16a (2) (missing prices); Mindestlohngesetz (MiLoG), minimum wage of 13,90 EUR since 2026-01-01; Umsatzsteuergesetz (UStG) § 12 (1): value added tax of 19 %
- Parameters:
  - `code_field` (plan or profile): `item_code`. Field holding the position number.
  - `unit_price_field` (plan or profile): `unit_price`. Field holding the unit price.
  - `item_type_field` (plan or profile): `item_type`. Field holding the item type (GAEB Positionsart).
  - `token_prices` (profile): `["0.01"]`. Unit prices that stand for no price (token_price); 0,00 is zero_price.
  - `excluded_item_type_pattern` (profile): `\bentfällt\b|\bnicht\s+angeboten\b`. Item types whose zero or token price is no finding (entfällt, nicht angeboten).
  - `not_offered_pattern` (profile): `\bnicht\s+angeboten\b`. Item types of a position not offered.
  - `undetermined_count_warnings` (profile): `[]`. Extraction warning codes of a file that does not say which positions count toward the totals (a GAEB X84 or D84 bid).
  - `undetermined_count_note` (profile): ``. What a not_offered finding in such a file says about counting.
  - `hourly_wage_floor` (profile): `13.90`. Lowest hourly labour rate, in floor_currency: the statutory minimum wage in Germany (Mindestlohngesetz), 13.90 EUR gross per hour since 2026-01-01. Update it each January.
  - `floor_currency` (profile): `EUR`. Currency of the hourly wage floor.
  - `floor_source` (profile): `statutory minimum wage (MiLoG), 13,90 EUR gross per hour since 2026-01-01`. Source of the floor, as shown.
  - `hourly_item_type_pattern` (profile): `\bstundenlohnarbeiten\b`. Item types of hourly work.
  - `hour_unit_ids` (profile): `["h"]`. Unit ids (of the unit catalogue) of an hour.
  - `labour_pattern` (profile): `\b(?:bau)?facharbeiter\w*|\bbauwerker\w*|\b(?:bau|hilfs)?helfer\w*|\b(?:bau|hilfs)?arbeiter\w*|\b(?:ober)?monteur\w*|\bvorarbeiter\w*|\bpolier(?:e|s|in|innen)?\b|\blohn\w*|\barbeitsstunden?\b|\bstundenlohn\w*|\bbedienung\w*|\bbediener\w*|\bfahrer\b|\bmaschinenführer\w*|\bingenieur\w*|\b(?:projekt|bau)leiter\w*`. Words that make a position in hours hourly labour (Facharbeiter, Helfer).
  - `credit_pattern` (profile): `\b(?:gutschrift\w*|rückvergütung\w*|rückerstattung\w*|\w*erlös\w*|abzug|abzüge|abzüglich|minder(?:kosten|preis\w*|ung\w*|vergütung\w*)|nachlass\w*|rabatt\w*|skonto)\b`. Words of a position that is a credit or deduction on purpose (Gutschrift, Abzug, Nachlass): its negative unit price is no finding.
  - `vat_rates` (profile): `["19"]`. Value added tax rates in percent that tax_in_unit_price looks for in a unit price (Germany: 19).

## domain.boq_clauses

**Bill clauses (risk, assumptions, vague wording, references)** (version 1.1.0). Reads the short and long texts of a German bill of quantities for clauses a bidder must price or ask about: costs put into the unit prices (ground, water, shoring, time and weather, work of others), conditions stated as assumptions, decisions left until later, open-ended or vague wording, lump sums whose scope depends on the effort, and references to plans or reports outside the bill.

- Applies when: Tables that map the short or the long description.
- Required fields: `description`; optional: `long_description`, `item_code`, `unit`, `item_type`
- Evidence classes: `semantic_warning`, `needs_external_context`
- Issue categories: `contract_clause`, `wording`, `lump_sum`, `reference`
- Finding category: `risk`; rule `assumed_condition`: `change_order_opportunity`; rule `deferred_decision`: `change_order_opportunity`; rule `document_reference`: `ambiguity`; rule `vague_wording`: `ambiguity`
- Limitations:
  - Clauses are found by German word lists, not understood: a clause worded otherwise is missed, and a listed word used in another sense can be reported.
  - Only the texts of positions and of their continuation lines are read; notes and preliminary texts that stand on their own are not.
  - Risk-shifting clauses are found where a subject and a shift phrase stand within a configured distance in one sentence; a clause that spreads over two sentences is missed.
- References: VOB/A 2019 § 7 (1) Nr. 6 (site conditions must be described); VOB/B § 2 (6) (claims for additional work are announced before the work starts); BGH, decision of 18 May 2004, X ZB 7/04 (no costs moved into other positions)
- Parameters:
  - `code_field` (plan or profile): `item_code`. Field holding the position number.
  - `description_field` (plan or profile): `description`. Field holding the short text (Kurztext).
  - `long_description_field` (plan or profile): `long_description`. Field holding the long text (Langtext).
  - `item_type_field` (plan or profile): `item_type`. Field holding the item type (GAEB Positionsart).
  - `note_item_type_pattern` (profile): `\bhinweis\b|\bausführungsbeschreibung\b|\bvorbemerkung\b`. Item types of notes that stand on their own (Hinweis): not item text.
  - `risk_subjects` (profile): `[{"subject": "ground", "label": "the ground (soil, rock, obstacles, existing utilities)", "pattern": "\\bbodenklassen?\\b|\\bhomogenbereich(?:e|en|es|s)?\\b|\\bbodenverhältnissen?\\b|\\bbaugrund(?:es|s)?\\b|\\bfels\\w*|\\bgesteins?\\b|\\bgesteine\\b|\\bgesteinsfestigkeit(?:en)?\\b|\\bhindernis(?:se|sen)?\\b|\\bfindling(?:e|en)?\\b|\\bsparten\\b|\\bbestandsleitung(?:en)?\\b|\\bvorhandene[nr]?\\s+(?:[\\w-]+\\s+){0,3}?[\\w-]*leitungen\\b|\\bmaschinenschachtung\\b", "severity": "medium"}, {"subject": "water", "label": "water (groundwater, dewatering, surface water)", "pattern": "\\bgrundwasser\\w*|\\bwasserhaltung\\w*|\\bschichtenwasser\\w*|\\btagw[aä]sser\\w*|\\bregenwasser\\b|\\boberflächenwasser\\w*|\\bsickerwasser\\w*", "severity": "medium"}, {"subject": "shoring", "label": "shoring and slopes (Verbau, Böschung)", "pattern": "\\b(?:graben)?verbau(?:s|es)?\\b|\\bböschung\\w*|\\bgeböscht\\w*", "severity": "medium"}, {"subject": "time_weather", "label": "construction time, weather and hindrance", "pattern": "\\bbauzeit\\b|\\bbauzeitverlängerung(?:en)?\\b|\\bwinter(?:bau|monate|monaten|zeit|liche[nmrs]?)?\\b|\\bfrost(?:es|perioden?|tagen?)?\\b|\\bwitterung(?:en|seinflüssen?|sbedingte?[nmrs]?|sverhältnissen?)?\\b|\\bschlechtwetter\\w*|\\bbehinderung(?:en)?\\b", "severity": "low"}, {"subject": "interfaces", "label": "work of the client, other trades or third parties", "pattern": "\\bbauseit(?:s|ig\\w*)\\b|\\bandere[nrsm]?\\s+gewerke?n?\\b|\\bfremdfirm(?:a|en)\\b|\\bdurch\\s+dritte\\b|\\bvom\\s+(?:ag|auftraggeber)\\b", "severity": "low"}]`. Subjects whose cost a clause can put on the bidder, with their severity.
  - `shift_pattern` (profile): `(?<!\bnicht\s)(?<!\bnicht\smit\s)\b(?:einzukalkulieren|einzurechnen|einkalkuliert|eingerechnet|abgegolten)\b|\b(?:wird|werden)\s+(?:\w+\s+){0,2}?nicht\s+(?:gesondert|separat)\s+vergütet\b|\bkeine\s+(?:gesonderte|separate)\s+vergütung\b|(?<!\bnicht\s)\bim\s+einheitspreis\s+enthalten\b|\bträgt\s+der\s+(?:an|auftragnehmer|bieter)\b|\bzu\s+lasten\s+des\s+(?:an|auftragnehmers)\b`. Phrases that put a cost into the unit price (einzukalkulieren, abgegolten).
  - `paid_separately_pattern` (profile): `\b(?:wird|werden|ist|sind)\s+(?:(?!nicht\b)\w+\s+){0,2}?(?:gesondert|separat|extra)\s+(?:vergütet|abgerechnet|bezahlt)\b`. Phrases that pay a subject separately ('wird gesondert vergütet').
  - `max_subject_gap_chars` (profile): `100`. Most characters between a subject and a shift phrase of one sentence.
  - `assumed_condition_pattern` (profile): `\bvermutlich\w*|\bvoraussichtlich\w*|\bmutmaßlich\w*|\bvorläufig\s+(?:ermittelt|festgelegt|angenommen)\w*|\bnach\s+(?:derzeitigem|heutigem)\s+(?:kenntnis|wissens)stand\b|\buntersuchungsergebnisse?\s+liegen\s+noch\s+nicht\s+vor\b|\beventuell\s+auftretende[nmrs]?\b`. Phrases that state a condition as an assumption (vermutlich, vorläufig).
  - `deferred_decision_pattern` (profile): `\bendgültige[nr]?\s+(?:festlegung|entscheidung)\b|\berst\s+nach\b.{0,80}?\b(?:festgelegt|festlegung|festgestellt|entschieden|bestimmt)\b|\bwird\s+erst\s+(?:vor\s+ort|nach\s+freilegung)\s+(?:festgelegt|entschieden)\b`. Phrases that leave a decision until later (endgültige Festlegung).
  - `inclusion_pattern` (profile): `(?:\beinschl\.|\beinschließlich\b|\binkl\.|\binklusive\b)\s*(?:aller|sämtlicher|allem|sämtlichem)\s+(?:notwendigen|erforderlichen|erfordelichen|benötigten|notwendiger|erforderlicher)\s+(\S+)`. Open-ended inclusions; the one group is the first word of what is included.
  - `small_material_pattern` (profile): `^(?:befestigungs|montage|verbindungs|schrauben|dichtungs|klein|hilfs|verbrauchs)(?:-|material|mittel)|^zubehör`. First words of an inclusion that name small material (not reported).
  - `open_detail_pattern` (profile): `\bin\s+geeigneter\s+weise\b|\bnach\s+wahl\s+des\s+(?:an|auftragnehmers)\b|\bnach\s+(?:örtlichem\s+)?erfordernis\b|\bnach\s+bedarf\b|\bsinngemäß\w*\b(?!\s+(?:wie\s+(?:in\s+)?)?(?:pos(?:ition)?|oz)\b\.?\s*\d)`. Phrases that leave a detail open (in geeigneter Weise, nach Bedarf).
  - `lump_sum_units` (profile): `["psch", "pauschal", "pa"]`. Unit texts of a lump sum besides the units of the lump sum dimension.
  - `lump_sum_item_type_pattern` (profile): `\bpauschalposition\b`. Item types of a lump sum.
  - `open_lump_sum_pattern` (profile): `\bnach\s+tatsächlich(?:em|en|er)?\s+(?:anfallende[mn]\s+)?(?:stunden)?aufwand\b|\bnach\s+(?:tatsächlichem\s+)?aufwand\b|\bnach\s+bedarf\b|\bnach\s+(?:örtlichem\s+)?erfordernis\b|\bjede[rnms]?\s+charge\b|\bje\s+charge\b|\bnach\s+aufmaß\b|\bmengenermittlung\s+nach\b|\bnach\s+anfall\b`. Phrases that make a lump sum depend on an unknown amount (je Charge).
  - `document_reference_pattern` (profile): `(?:\bgem\.|\bgemäß\b|\blt\.|\blaut\b|\bsiehe\b|\bs\.|\bnach\b|\bentsprechend\b|\bbeiliegende[rmns]?\b)\s*(?:[\w./-]+\s+){0,2}?(?:pläne|plänen|plan|zeichnungen|zeichnung|statik|statische[nrs]?\s+berechnung(?:en)?|details?|bodengutachten|baugrundgutachten|gutachten|geotechnische[rn]?\s+bericht\w*|lageplan|leitungsplan|anlage\s+\d+|regelzeichnung(?:en)?|regelblatt|systemskizze|skizze|fließbild)\b`. References to plans, drawings, calculations and reports.
  - `max_quotes` (profile): `3`. Clauses quoted in one finding.
  - `max_cells_per_issue` (profile): `20`. Cells highlighted in one finding.

## domain.boq_companion_work

**Companion work (BoQ)** (version 1.0.0). Lists work a bill of quantities describes without the work that goes with it: wall penetrations without a seal, site equipment set up and cleared but not kept on site, pressure pipes without a pressure test, excavation without backfill. One finding per bill and pair, listing the positions.

- Applies when: Tables that map the item description (Kurztext).
- Required fields: `description`; optional: `long_description`, `item_code`, `unit`
- Evidence classes: `semantic_warning`
- Issue categories: `companion_work`
- Finding category: `omission`
- Limitations:
  - Reads German wording only; the companion can be priced in a position whose wording does not name it, so every finding needs a reviewer.
  - A bill whose items have no Langtext is not checked (a bid file with Kurztexts only names too little).
  - The default word lists were measured on five sample bills; other bills may word the same work differently.
- Parameters:
  - `description_field` (plan or profile): `description`. Kurztext field.
  - `long_description_field` (plan or profile): `long_description`. Langtext field.
  - `item_code_field` (plan or profile): `item_code`. OZ field.
  - `pairs` (profile): `[{"rule_id": "penetration_without_seal", "title": "Wall penetrations without a seal", "described": "pipes passing through walls (core holes, wall ducts or sleeves)", "missing": "no position seals them", "companion_words": "Ringraumdichtung, Dichtungseinsatz, Link-Seal, Pressio, Mediendurchführung, Durchführungsdichtung, gas-/wasserdicht, Brandschott, Abschottung, Brandschutzmanschette", "triggers": [{"name": "Wanddurchführung", "pattern": "kern(?:loch)?bohrung|wanddurchf(?:ü|ue)hrung|mauerdurchf(?:ü|ue)hrung|futterrohr|hauseinf(?:ü|ue)hrung|geb(?:ä|ae)udeeinf(?:ü|ue)hrung"}], "trigger_requires": [], "trigger_exclude": "\\b(?:ausbau|ausbauen|r(?:ü|ue)ckbau|r(?:ü|ue)ckbauen|demontage|demontieren|verschlie(?:ß|ss)en|verf(?:ü|ue)llen|abdichten)\\b|kernbohrger", "own_text_pattern": "ringraum|dichtungseinsatz|link-?seal|pressio|mediendurchf(?:ü|ue)hrung|durchf(?:ü|ue)hrungsdichtung|(?:gas|wasser|druckwasser)dicht|gas-\\s*(?:und|u\\.|/)\\s*(?:druck)?wasserdicht|brandschott|abschottung|brandschutzmanschette", "companion_pattern": "ringraumdichtung|dichtungseinsatz|link-?seal|mediendurchf(?:ü|ue)hrung|durchf(?:ü|ue)hrungsdichtung|brandschott|abschottung|brandschutzmanschette", "companion_text": "item_descriptions", "companion_same_term": false, "companion_time_unit": false, "scope": "bill", "severity": "medium", "recommendation": "Ask a bidder question: which position pays for sealing these wall penetrations (gas- and watertight annular seals, or firestopping in a fire-rated wall)? Do not add a position to the bill. If none pays for it, this may become a change order after award, subject to the contract."}, {"rule_id": "site_equipment_without_upkeep", "title": "Site equipment set up and cleared, but not kept on site", "described": "site equipment that is set up and cleared", "missing": "no position in the same section keeps that equipment on site (vorhalten) or is priced per unit of time", "companion_words": "vorhalten, Vorhaltung, unterhalten, Unterhaltung, or a unit of time", "triggers": [{"name": "Bauzaun", "pattern": "bauz(?:ä|ae)un(?:e|en)?\\b|bauzaun\\w*"}, {"name": "Absperrung", "pattern": "absperrung(?:en)?\\b|absperrgitter|absperrschranke"}, {"name": "Container", "pattern": "container"}, {"name": "Baustraße", "pattern": "baustra(?:ß|ss)e"}, {"name": "Überfahrt", "pattern": "(?:ü|ue)berfahrt"}, {"name": "Beleuchtung", "pattern": "beleuchtung|warnleuchte"}, {"name": "Verkehrszeichen", "pattern": "verkehrszeichen|beschilderung"}, {"name": "Schutzgerüst", "pattern": "schutzger(?:ü|ue)st"}, {"name": "Rohrbrücke", "pattern": "rohrbr(?:ü|ue)cke"}, {"name": "Baustellenampel", "pattern": "baustellenampel|lichtsignalanlage"}], "trigger_requires": ["\\b(?:aufstellen|herstellen|einrichten|errichten|aufbauen|montieren)\\b", "\\b(?:r(?:ä|ae)umen|beseitigen|abbauen|entfernen|r(?:ü|ue)ckbauen|demontieren)\\b"], "trigger_exclude": null, "own_text_pattern": null, "companion_pattern": "\\b(?:vorhalten|vorhaltung|vorhaltezeit|vorhaltedauer|unterhalten|unterhaltung)\\b", "companion_text": "item_descriptions", "companion_same_term": true, "companion_time_unit": true, "scope": "top_section", "severity": "medium", "recommendation": "Ask a bidder question: which position pays for keeping this equipment on site (vorhalten) for the construction period? Price the set-up and clearing as the positions describe them, and never price the upkeep into other positions (BGH, X ZB 7/04). If none pays for it, this may become a change order after award, subject to the contract."}, {"rule_id": "pipe_without_pressure_test", "title": "Pressure pipes without a pressure test", "described": "laying pressure or drinking-water pipes", "missing": "no text of the bill names a pressure or leak test", "companion_words": "Druckprüfung, Druckprobe, Dichtheitsprüfung, Dichtigkeitsprüfung", "triggers": [{"name": "Druckrohrleitung", "pattern": "druckrohr(?:leitung)?|trinkwasserleitung|wasserleitung|k(?:ä|ae)ltefernleitung|fernk(?:ä|ae)lteleitung|wasserltg|druckleitung"}], "trigger_requires": ["\\bverleg|\\beinbau|\\bmontier"], "trigger_exclude": null, "own_text_pattern": null, "companion_pattern": "druckpr(?:ü|ue)fung|druckprobe|dichtheitspr(?:ü|ue)fung|dichtheitsprobe|dichtigkeitspr(?:ü|ue)fung|dichtigkeitsprobe", "companion_text": "all_texts", "companion_same_term": false, "companion_time_unit": false, "scope": "bill", "severity": "medium", "recommendation": "Ask a bidder question: which position pays for the pressure test of these pipes (and its records)? Do not add a position to the bill. If none pays for it, this may become a change order after award, subject to the contract."}, {"rule_id": "trench_without_backfill", "title": "Excavation without backfill", "described": "trench or pit excavation", "missing": "no text of the bill names backfilling", "companion_words": "verfüllen, Verfüllung, Rückverfüllung, Wiederverfüllung, Leitungszone, Hinterfüllung, einbauen und verdichten", "triggers": [{"name": "Graben", "pattern": "rohrgr(?:a|ä|ae)ben|leitungsgr(?:a|ä|ae)ben|kabelgr(?:a|ä|ae)ben|baugrube|\\bgr(?:a|ä|ae)ben\\b"}], "trigger_requires": ["aushub|ausheben|\\bl(?:ö|oe)sen|ausschachten|herstellen"], "trigger_exclude": null, "own_text_pattern": null, "companion_pattern": "verf(?:ü|ue)ll|leitungszone|hinterf(?:ü|ue)ll|(?:wieder)?anf(?:ü|ue)ll|einbauen,?\\s+(?:und\\s+)?verdichten|\\bboden\\b(?:\\W+\\w+){0,4}?\\W+einbauen", "companion_text": "all_texts", "companion_same_term": false, "companion_time_unit": false, "scope": "bill", "severity": "medium", "recommendation": "Ask a bidder question: which position pays for backfilling and compacting the excavation? Do not add a position to the bill. If none pays for it, this may become a change order after award, subject to the contract."}]`. Trigger work and the companion it needs (profile-controlled).
  - `time_dimensions` (profile): `["time", "count_time", "area_time"]`. Unit dimensions that price per unit of time (vorhalten per week).
  - `time_unit_texts` (profile): `["mwo", "mxwo", "md", "mxd", "m2d", "sttag", "stxtag"]`. Unit texts that price per unit of time but are not in the profile's unit list (compared as unit keys: case, spaces and dots ignored, m² as m2).
  - `max_cells_per_issue` (profile): `20`. Rows highlighted in one finding.

## domain.boq_contradictions

**Contradictions within an item** (version 1.2.0). Finds items that contradict themselves: a short text and long text naming different diameters, pressures, angles, concrete classes, steel grades, fire ratings or colours, or used against new material; a text measuring the item in another unit than its unit column; a text calling it a contingency or alternative item while it counts toward the total; a quantity in the text that differs from the item's quantity.

- Applies when: Tables that map the item description of a bill of quantities.
- Required fields: `description`; optional: `long_description`, `unit`, `quantity`, `item_type`, `item_code`
- Evidence classes: `semantic_warning`
- Issue categories: `contradiction`
- Finding category: `ambiguity`
- Limitations:
  - A long text may legitimately name several values (a connection from DN 150 to DN 100); a conflict is reported only when each text states a value the other does not repeat.
  - Only values written in both texts are compared: a value changed in a text whose counterpart does not state it at all is not found.
  - Units in texts are read through the profile's unit vocabulary; unknown ones are not compared.
- References: VOB/A § 7 (1) Nr. 1: the description of the work must be unambiguous.
- Parameters:
  - `code_field` (plan or profile): `item_code`. Field holding the item number.
  - `description_field` (plan or profile): `description`. Short text field.
  - `long_description_field` (plan or profile): `long_description`. Long text field (needed for spec_conflict).
  - `quantity_field` (plan or profile): `quantity`. Field holding the quantity.
  - `item_type_field` (plan or profile): `item_type`. Field holding the item type.
  - `specifications` (profile): `["nominal_diameter", "pressure_rating", "pressure_bar", "angle", "material_condition", "concrete_class", "steel_grade", "fire_rating", "sdr", "ral", "soil_class"]`. Kinds of specification compared between short and long text: nominal_diameter, pressure_rating, pressure_bar, angle, material_condition, concrete_class, steel_grade, fire_rating, sdr, ral, soil_class

## domain.boq_description_clarity

**Unclear or incomplete descriptions** (version 1.0.0). Reads item texts as a tender estimator prices them: text left to be filled in, items that only refer back with nothing before them, scope or decisions left open, bare short texts in a bill of long texts; and, per table, catch-all wording and items the bidder must complete.

- Applies when: Tables that map the item description of a bill of quantities.
- Required fields: `description`; optional: `long_description`
- Evidence classes: `semantic_warning`, `needs_external_context`
- Issue categories: `unclear_description`, `bidder_input`
- Finding category: `ambiguity`; rule `open_decision`: `change_order_opportunity`
- Limitations:
  - Wording is matched as phrases; it says where a description may be unclear, not that it is. A reviewer decides.
  - German and English wording by default; other languages need profile phrases.
- References: VOB/A § 7 (1) Nr. 1 and 3: the description of the work must be clear and complete and must not put an unusual risk on the bidder.
- Parameters:
  - `code_field` (plan or profile): `item_code`. Field holding the item number.
  - `description_field` (plan or profile): `description`. Short text field.
  - `long_description_field` (plan or profile): `long_description`. Long text field (used when mapped).
  - `item_type_field` (plan or profile): `item_type`. Item type field (GAEB Positionsart; used when mapped).
  - `placeholder_phrases` (profile): `["???", "xxx", "xxxx", "tbd", "tba", "tbc", "n.n.", "noch festzulegen", "noch offen", "noch zu klären", "noch zu bestimmen", "wird nachgereicht", "text folgt", "angaben folgen", "beschreibung folgt", "to be confirmed", "to be determined", "to be advised"]`. Text left to be filled in.
  - `relative_phrases` (profile): `["wie vor", "wie vorher", "wie vorbeschrieben", "wie vorstehend", "dto.", "dito", "desgl.", "jedoch", "as before", "ditto", "as above"]`. Wording that only refers to the item before.
  - `open_scope_phrases` (profile): `["nach Bedarf", "bei Bedarf", "nach Erfordernis", "nach Erfordernissen", "nach Notwendigkeit", "je nach Bedarf", "je nach Erfordernis", "nach Aufwand", "je nach Aufwand", "as required", "if required", "where required", "as necessary", "if necessary"]`. Wording that leaves scope open.
  - `open_decision_phrases` (profile): `["nach Wahl des AG", "nach Wahl des Auftraggebers", "nach Wahl der Bauleitung", "nach Wahl des Architekten", "nach Angabe des AG", "nach Angabe des Auftraggebers", "nach Angabe der Bauleitung", "nach Angabe des Architekten", "nach Angabe der BL", "nach Anweisung des AG", "nach Anweisung der Bauleitung", "nach Anordnung des AG", "nach Anordnung der Bauleitung", "nach Vorgabe des AG", "nach Vorgabe der Bauleitung", "nach Absprache", "nach Abstimmung", "in Absprache mit", "nach Rücksprache", "as directed", "as instructed", "to the engineer's approval", "to be agreed"]`. Wording that leaves the decision to the client later.
  - `catch_all_phrases` (profile): `["einschl. aller", "einschließlich aller", "inkl. aller", "inklusive aller", "einschl. sämtlicher", "inkl. sämtlicher", "komplett", "betriebsfertig", "schlüsselfertig", "o.ä.", "o. ä.", "oder ähnlich", "u.ä.", "u. ä.", "etc.", "usw.", "u. dgl.", "u.dgl.", "und dergleichen", "or similar", "and the like", "complete with all"]`. Open-ended or catch-all wording.
  - `bidder_input_phrases` (profile): `["angebotenes Fabrikat", "angebotener Typ", "angebotenes Produkt", "angebotenes System", "angebotener Hersteller", "vom Bieter einzutragen", "vom Bieter anzugeben", "vom Bieter einzusetzen", "Bieterangabe", "Angaben des Bieters", "bidder to state", "tenderer to state"]`. Wording that asks the bidder to state something.
  - `short_text_max_chars` (profile): `30`. A short text up to this length is 'a few words'.
  - `full_text_median_chars` (profile): `150`. Median text length from which a bill counts as written in long texts.
  - `max_listed` (profile): `12`. Items named in a summary.

## domain.boq_numbering

**Missing items in the numbering** (version 1.0.0). Reads the item numbers (OZ) of a bill for completeness: numbers skipped in an otherwise regular sequence, items filed under a section whose number they do not carry, and numbered section headings without any item.

- Applies when: Tables that map the item number of a bill of quantities.
- Required fields: `item_code`; optional: `description`
- Evidence classes: `suspected_anomaly`
- Issue categories: `missing_item`, `numbering`
- Finding category: `omission`; rule `misplaced_item`: `error`
- Limitations:
  - Numbers are often removed on purpose (a deleted item); a gap is a question for the client, not an error.
  - Only numeric last parts are compared; numbers with letters (1.2.10a) are skipped for gaps.
- References: VOB/A § 7 (1): the description of the work must be complete; GAEB OZ structure (ordinal numbers by level).
- Parameters:
  - `code_field` (plan or profile): `item_code`. Field holding the item number.
  - `description_field` (plan or profile): `description`. Field holding the short text (named in findings).
  - `min_items` (profile): `4`. Numbers in a group before its gaps are judged.
  - `regular_share` (profile): `0.75`. Share of a group's steps that must equal its most common step.
  - `max_missing` (profile): `3`. Most numbers one reported gap may span.

## domain.boq_position_types

**Contingency positions and hourly work** (version 1.0.0). Lists the contingency positions (Bedarfspositionen, Eventualpositionen) and the hourly work of a bill of quantities, with or without total, so that the bidder prices them at rates that cover cost: the client may order them at these prices.

- Applies when: Tables that map the item type, the short or the long description.
- Required fields: `description`; optional: `item_type`, `long_description`, `item_code`, `unit`
- Evidence classes: `semantic_warning`
- Issue categories: `position_type`
- Finding category: `risk`
- Limitations:
  - A contingency position is recognised by its GAEB item type or by the words of its text; one marked only by a section heading is missed.
  - Hourly work in an hour unit is recognised only when its text names labour (Facharbeiter, Helfer, Lohn, ...); plant hired by the hour is not listed.
- References: VOB/A 2019 § 7 (1) Nr. 4 (contingency positions and hourly work)
- Parameters:
  - `code_field` (plan or profile): `item_code`. Field holding the position number.
  - `description_field` (plan or profile): `description`. Field holding the short text (Kurztext).
  - `long_description_field` (plan or profile): `long_description`. Field holding the long text (Langtext).
  - `item_type_field` (plan or profile): `item_type`. Field holding the item type (GAEB Positionsart).
  - `note_item_type_pattern` (profile): `\bhinweis\b|\bausführungsbeschreibung\b|\bvorbemerkung\b`. Item types of notes that stand on their own (Hinweis): not item text.
  - `contingency_item_type_pattern` (profile): `\b(?:bedarfs|eventual)position\b|^\s*(?:bmgb|emgb|bogb|eogb|b\s*[mo]\.?\s*gb|b|e|bedarf|eventual|contingency)\s*$`. Item types of contingency positions.
  - `contingency_text_pattern` (profile): `\bbedarfsposition(?:en)?\b|\beventualposition(?:en)?\b|\bnur\s+auf\s+(?:besondere\s+)?anordnung\s+(?:des\s+ag|des\s+auftraggebers)\b|\bnach\s+besonderer\s+anordnung\b`. Texts that make a position a contingency position (Eventualposition).
  - `with_total_pattern` (profile): `\bmit\s+(?:gb|gesamtbetrag)\b|^\s*(?:bmgb|emgb|b\s*m\.?\s*gb)\s*$`. Contingency positions with a total (mit GB).
  - `without_total_pattern` (profile): `\bohne\s+(?:gb|gesamtbetrag)\b|^\s*(?:bogb|eogb|b\s*o\.?\s*gb)\s*$`. Contingency positions without a total (ohne GB).
  - `hourly_item_type_pattern` (profile): `\bstundenlohnarbeiten\b`. Item types of hourly work.
  - `hour_unit_ids` (profile): `["h"]`. Unit ids (of the unit catalogue) of an hour.
  - `labour_pattern` (profile): `\b(?:bau)?facharbeiter\w*|\bbauwerker\w*|\b(?:bau|hilfs)?helfer\w*|\b(?:bau|hilfs)?arbeiter\w*|\b(?:ober)?monteur\w*|\bvorarbeiter\w*|\bpolier(?:e|s|in|innen)?\b|\blohn\w*|\barbeitsstunden?\b|\bstundenlohn\w*|\bbedienung\w*|\bbediener\w*|\bfahrer\b|\bmaschinenführer\w*|\bingenieur\w*|\b(?:projekt|bau)leiter\w*`. Words that make a position in hours hourly labour (Facharbeiter, Helfer).
  - `max_cells_per_issue` (profile): `20`. Cells highlighted in one finding (its evidence lists every position).

## domain.boq_required_attributes

**Required attributes (BoQ)** (version 1.0.0). Lists positions of a bill of quantities whose price depends on a property the text does not state: disposal without a waste class, concrete without a strength class, pipes and fittings without a dimension. One finding per bill and rule, listing the positions.

- Applies when: Tables that map the item description (Kurztext).
- Required fields: `description`; optional: `long_description`, `item_code`
- Evidence classes: `semantic_warning`
- Issue categories: `missing_attribute`
- Finding category: `ambiguity`
- Limitations:
  - Reads German wording only; the attribute can be stated in a drawing, the preamble or a note the check does not read, so every finding needs a reviewer.
  - The default word lists were measured on five sample bills; other bills may word the same work or attribute differently.
- Parameters:
  - `description_field` (plan or profile): `description`. Kurztext field.
  - `long_description_field` (plan or profile): `long_description`. Langtext field.
  - `item_code_field` (plan or profile): `item_code`. OZ field.
  - `rules` (profile): `[{"rule_id": "disposal_waste_class", "title": "Disposal without a waste class", "described": "the disposal of soil, rubble or filter material", "attribute": "waste class", "triggers": [[{"pattern": "entsorg|deponie|deponier|verwert", "part": "description", "at_start": false}, {"pattern": "boden|aushub|bodendecke|oberboden|mutterboden|bauschutt|beton|asphalt|fr(?:ä|ae)sgut|filter|st(?:ü|ue)tzschicht|\\bkies|schotter|schlamm|bankett|tragschicht|pflaster|mauerwerk", "part": "both", "at_start": false}]], "excludes": [{"pattern": "entsorgungsleitung|ver-\\s*/?\\s*(?:und\\s+)?entsorgungs(?:ltg|leitung)|entsorgungsltg|entsorgungseinr|entsorgungstr(?:ä|ae)ger|ver-\\s*und\\s+entsorgung|rohrleitung|armatur|formst(?:ü|ue)ck|stahl|metall|schrott|kabel|\\breinig(?:en|ung)\\b|\\bs(?:ä|ae)ubern\\b|\\bkehren\\b", "part": "description", "at_start": false}], "ignore_in_description": null, "attribute_pattern": "\\bZ\\s?0\\b|\\bZ\\s?0\\*|\\bZ\\s?1[.,][12]\\b|\\bZ\\s?2\\b|>\\s*Z\\s?2|\\bDK\\s?(?:0|I{1,3}|[0-3])\\b|deponieklasse|\\bLAGA\\b|\\bDepV\\b|deponieverordnung|\\bAVV|abfallschl(?:ü|ue)ssel|(?<!\\d)(?:0[1-9]|1\\d|20)(?: \\d{2} \\d{2}|\\d{4})\\*?(?![\\d.,])|\\bBM-?F?[0-3]\\*?|\\bRC-?[1-3]\\b|ersatzbaustoffverordnung|\\bEBV\\b|unbelastet|schadstoffbelastet|\\bgef(?:ä|ae)hrlich|deklarationsanalyse|einbauklasse|verwertungsklasse|teerhaltig|pechhaltig|\\bPAK\\b", "open_pattern": "noch\\s+(?:festzulegen|zu\\s+bestimmen|offen)|wird\\s+(?:noch\\s+)?festgelegt|nach\\s+(?:analyse|beprobung)\\s+festzulegen", "neighbour_example": false, "severity": "medium", "recommendation": "Ask a bidder question: which waste class (an AVV code, a class under the Ersatzbaustoffverordnung or the DepV) should the disposal price assume, or is there an analysis? Disposal prices depend on the class. If another class is found after award, that may become a change order, subject to the contract."}, {"rule_id": "concrete_strength_class", "title": "Concrete without a strength class", "described": "concrete made or placed on site", "attribute": "strength class", "triggers": [[{"pattern": "\\b(?:ortbeton|normalbeton|unterbeton|magerbeton)|sauberkeitsschicht\\s+aus\\s+beton|betonfundament|fundament\\w*\\s+aus\\s+beton|\\bbeton\\b(?:\\W+\\w+){0,3}?\\W+(?:herstellen|liefern|einbauen|einbringen)\\b|\\b(?:stahlbeton\\w*|transportbeton(?![\\w-]))(?:\\W+\\w+){0,4}?\\W+(?:herstellen|liefern|einbauen|einbringen|betonieren)\\b", "part": "description", "at_start": false}], [{"pattern": "\\b(?:ortbeton|normalbeton|unterbeton|magerbeton)|sauberkeitsschicht\\s+aus\\s+beton", "part": "long_description", "at_start": false}]], "excludes": [{"pattern": "abbrechen|abbruch|ausbauen|\\bausbau\\b|aufnehmen|entsorg|fertigteil|vorgefertigt|betonrohr|betonstein|bordstein|pflaster|betonplatte|schacht|rinne|betonring|brunnenring|betonf(?:ü|ue)llung|kernbohrung", "part": "both", "at_start": false}, {"pattern": "\\A\\W*(?:\\w+\\W+){0,2}?(?:schalung|bewehrung|betonstahl|beschicht|anstrich|impr(?:ä|ae)gnier|oberfl(?:ä|ae)chenschutz|s(?:ä|ae)gen|schneiden|durchbruch|bohrung|aussparung|schlitz)", "part": "description", "at_start": false}], "ignore_in_description": null, "attribute_pattern": "\\bL?C\\s?\\d{1,3}\\s?/\\s?\\d{1,3}\\b|festigkeitsklasse", "open_pattern": null, "neighbour_example": true, "severity": "medium", "recommendation": "Ask a bidder question for the missing strength class: without it the price cannot be calculated."}, {"rule_id": "pipe_dimension", "title": "Pipes or fittings without a dimension", "described": "the supply or laying of pipes or fittings", "attribute": "dimension (DN, OD or diameter)", "triggers": [[{"pattern": "^(?:[^\\w-]|-(?![\\w-]))*[\\w-]*?(?:rohr(?:e|es|en)?|rohrleitung(?:en)?|b(?:ö|oe)gen|bogen|winkel|t-st(?:ü|ue)ck(?:e)?|reduzierst(?:ü|ue)ck(?:e)?|muffe(?:n)?|flansch(?:e|es|en)?|kappe(?:n)?|schieber)(?![\\w-])", "part": "description", "at_start": true}], [{"pattern": "(?<![\\w-])[\\w-]*?(?:rohr(?:e|es|en)?|rohrleitung(?:en)?|b(?:ö|oe)gen|bogen|winkel|t-st(?:ü|ue)ck(?:e)?|reduzierst(?:ü|ue)ck(?:e)?|muffe(?:n)?|flansch(?:e|es|en)?|kappe(?:n)?|schieber)(?![\\w-])", "part": "description", "at_start": false}, {"pattern": "\\b(?:liefern|verlegen|einbauen|montieren|einschwei(?:ß|ss)en|setzen|herstellen|einziehen|anschlie(?:ß|ss)en)\\b", "part": "description", "at_start": false}]], "excludes": [{"pattern": "trassenband|warnband|markier|einbettung|bettung|\\bsand\\b|schutzrohr|sichern|ausbau|ausbauen|r(?:ü|ue)ckbau|demontage|demontieren|abbrechen|abbruch|entsorg|stilllegen|verd(?:ä|ae)mmen|verf(?:ü|ue)llen|sp(?:ü|ue)len|reinigen|befahren|inspektion|tv-", "part": "description", "at_start": false}], "ignore_in_description": "stra(?:ß|ss)enkappe|schutzkappe|kunststoffkappe|rohrgraben|rohrpfosten|rohrbr(?:ü|ue)cke|rohrdurchf(?:ü|ue)hrung|rohrabsperrblase|futterrohr|schutzrohr|leerrohr|mantelrohr", "attribute_pattern": "\\bDN\\b|\\bDN\\s?\\d|\\bOD\\b|\\bOD\\s?\\d|\\bDA\\b|\\bDA\\s?\\d|\\bAD\\b|\\bAD\\s?\\d|\\bd\\s?=|\\bd\\s?\\d|\\bda\\s?\\d|[Øø⌀]|au(?:ß|ss)endurchmesser|nennweite|innendurchmesser|durchmesser|\\bdurchm\\.?|\\d+(?:[.,]\\d+)?\\s?x\\s?\\d+(?:[.,]\\d+)?|\\d+(?:[.,]\\d+)?\\s?mm\\b|\\d+(?:[.,]\\d+)?\\s?cm\\b|\\bnw\\s?\\d|\\b\\d+\\s?zoll\\b|\\d+\\s?\\\"|\\b[1-9]/[248]\\s?\\\"", "open_pattern": null, "neighbour_example": true, "severity": "medium", "recommendation": "Ask a bidder question for the missing dimension (DN, OD or diameter): without it the price cannot be calculated."}]`. Work and the attribute its price needs (profile-controlled).
  - `max_cells_per_issue` (profile): `20`. Rows highlighted in one finding.

## domain.boq_separate_payment

**Paid separately, without a paying position (BoQ)** (version 1.1.0). Lists clauses of a bill of quantities that say work is paid separately ('wird gesondert vergütet') when no other position names that work. One finding per bill. Not run by default: about half of what it lists is paid under another name.

- Applies when: Tables that map the item description (Kurztext).
- Required fields: `description`; optional: `long_description`, `item_code`
- Evidence classes: `semantic_warning`
- Issue categories: `separate_payment`
- Finding category: `omission`
- Limitations:
  - Matches words, not meaning: a position that pays for the work under another name is not recognised unless the synonym map names it.
  - Measured on five sample bills: about half of the listed clauses had a paying position under another name.
- Parameters:
  - `description_field` (plan or profile): `description`. Kurztext field.
  - `long_description_field` (plan or profile): `long_description`. Langtext field.
  - `item_code_field` (plan or profile): `item_code`. OZ field.
  - `clause_pattern` (profile): `\b(?:wird|werden)\s+(?:gesondert|separat)\s+verg(?:ü|ue)tet\b`. The clause that says another position pays (profile-controlled).
  - `synonyms` (profile): `{"bettung": ["sand", "kies", "bettungsmaterial", "leitungszone", "rohrbettung"], "form- und verbindungsstücke": ["bogen", "winkel", "t-stück", "reduzier", "muffe", "flansch", "formteil"], "formstücke": ["bogen", "winkel", "t-stück", "reduzier", "muffe", "flansch", "formteil"], "verbau": ["verbau", "grabenverbau"], "wasserhaltung": ["wasserhaltung", "pumpe"], "gerüst": ["gerüst"], "suchgr": ["suchschlitz", "suchschacht", "suchgrab", "suchgräb", "probeschurf"], "wiederanfüllung": ["verfüll", "anfüll", "hinterfüll"], "anfüllung": ["verfüll", "anfüll", "hinterfüll"]}`. Head noun (start or end of it; a key with a space: the phrase) -> other words a paying position may use (lower case, matched as parts of words).
  - `max_cells_per_issue` (profile): `20`. Rows highlighted in one finding.

## domain.boq_tender_comparison

**Bid against its tender** (version 1.0.0). Compares each position of a priced bill with the tender it answers (an unpriced bill of the same project whose positions match): positions added or missing, and quantities, units and texts that differ. Finds a changed quantity whose line total and sums were recomputed to match, which no check of the bill alone can see.

- Applies when: Priced bills whose project holds their tender: an unpriced bill where at least half of the bill's positions have the same item number with the same quantity or short text.
- Required fields: `item_code`; optional: `description`, `long_description`, `quantity`, `unit`, `unit_price`, `line_total`, `discount_percent`, `currency`
- Evidence classes: `confirmed_rule_violation`
- Issue categories: `tender_comparison`
- Finding category: `inconsistency`; rule `tender_position_missing`: `omission`
- Limitations:
  - Positions are paired by item number only; a position that moved to another number shows as one added and one missing.
  - Texts are compared word by word without regard to case and spacing; a change of punctuation alone is reported.
  - A difference says the bid and the tender disagree; in a contract or a later revision it may be an agreed change order.
  - Measured on the two tender-bid pairs of the hackathon files only; the practice benchmark cannot measure it, because its clean bill is the answer key.
- References: VOB/A 2019 § 13 (1) Nr. 5 (no changes to the tender documents) and § 16 (1) Nr. 2 (such bids are excluded)

## domain.boq_typos

**Typing slips in texts** (version 1.1.0). Finds typing slips in item and section texts without a dictionary: a word repeated, a known misspelling, and a word used once that differs by one letter from a word the bill uses often (Auftragnehemer beside Auftragnehmer).

- Applies when: Tables that map the item description.
- Required fields: `description`; optional: `long_description`, `item_code`
- Evidence classes: `semantic_warning`
- Issue categories: `spelling`
- Finding category: `error`
- Limitations:
  - The bill is its own reference: a word misspelled the same way throughout is not found, and a rare correct word can resemble a frequent one.
  - Text read by OCR has more slips; they are reported like typed ones.
- Parameters:
  - `code_field` (plan or profile): `item_code`. Field holding the item number.
  - `description_field` (plan or profile): `description`. Short text field.
  - `long_description_field` (plan or profile): `long_description`. Long text field (used when mapped).
  - `misspellings` (profile): `{"seperat": "separat", "seperate": "separate", "seperaten": "separaten", "seperater": "separater", "standart": "Standard", "standartmäßig": "standardmäßig", "wiederrum": "wiederum", "entgültig": "endgültig", "entgültige": "endgültige", "vorraussetzung": "Voraussetzung", "vorraussetzungen": "Voraussetzungen", "vorraussichtlich": "voraussichtlich", "nähmlich": "nämlich", "reperatur": "Reparatur", "reperaturen": "Reparaturen", "rückgrad": "Rückgrat", "ingeneur": "Ingenieur", "aluminum": "Aluminium", "estrisch": "Estrich", "fasade": "Fassade", "addresse": "Adresse", "rhytmus": "Rhythmus", "agressiv": "aggressiv", "agressive": "aggressive", "nachvollziehbahr": "nachvollziehbar", "vorallem": "vor allem", "garnicht": "gar nicht", "zuende": "zu Ende", "tolleranz": "Toleranz", "tolleranzen": "Toleranzen", "brandschuz": "Brandschutz", "isoliertung": "Isolierung"}`. Known misspellings (lower case) and their correct form.
  - `min_length` (profile): `9`. Shortest word checked.
  - `min_frequent` (profile): `3`. How often the reference word must occur.
  - `transpositions` (profile): `true`. Count two swapped neighbouring letters as one edit.
  - `excluded_pairs` (profile): `[["leistung", "leitung"], ["schichten", "schächten"], ["auftrag", "austrag"], ["vermeiden", "vermieden"], ["beschreiben", "beschrieben"], ["vorgeschrieben", "vorbeschrieben"], ["verhalten", "vorhalten"], ["anzulegen", "abzulegen"], ["nahmen", "nehmen"]]`. Real words that differ by one letter; a pair also covers words that contain it (profile-controlled).
  - `excluded_prefixes` (profile): `[["ab", "an"], ["auf", "aus"]]`. Word-initial prefixes one letter apart that make two real words (Abtransport / Antransport); a pair differing only there is not reported.
  - `max_findings` (profile): `200`. Findings per table.

## domain.model_quantities

**Bill against model quantities (IFC)** (version 1.0.0). Compares each position's quantity with the base quantities of the elements an attached IFC model links to its item number, and reports item numbers the model has but the bill does not. Finds wrong quantities whose totals add up, which no check of the bill alone can see.

- Applies when: Bills with an attached IFC model whose elements carry classification references with the item numbers.
- Required fields: `item_code`, `quantity`, `unit`; optional: `unit_price`, `discount_percent`, `currency`
- Evidence classes: `confirmed_rule_violation`
- Issue categories: `model_quantity`
- Finding category: `inconsistency`; rule `model_position_missing`: `omission`
- Limitations:
  - Elements are linked to positions only by item number (classification reference); no text or geometry matching.
  - Quantities are the model's stated base quantities; geometry is not measured.
  - A difference says the bill and the model disagree, not which one is wrong; measurement rules (for example VOB/C deductions) can explain small ones.
  - Positions the model does not contain are not reported.
  - Measured only with a test model generated from the bill itself (an upper bound); the 5 % tolerance has not been checked against an independent design model.
- References: ISO 16739-1 (IFC): IfcElementQuantity, IfcRelAssociatesClassification
- Parameters:
  - `tolerance` (profile): `0.05`. Relative difference allowed between the bill's and the model's measured quantity (a bill rounds its quantities, and measurement rules differ from net geometry).
  - `high_from` (profile): `0.5`. High severity from.
  - `medium_from` (profile): `0.15`. Medium severity from.
  - `max_global_ids` (profile): `20`. Element ids listed.

## domain.standard_text_keys

**Standard text keys (STLB-Bau)** (version 1.0.0). Compares items that name the same standard text (an STLB-Bau, StLB or StLK key from a GAEB file): different units or unit prices for one standard text, and keys from several catalogues or catalogue versions. The licensed catalogue texts are not checked.

- Applies when: Tables that map the standard text key (GAEB bills whose items carry STLB-Bau or StLNo references).
- Required fields: `standard_text_key`; optional: `standard_text_catalog`, `unit`, `unit_price`
- Evidence classes: `semantic_warning`, `suspected_anomaly`, `needs_external_context`
- Issue categories: `unit`, `unit_price`, `standard_text`
- Finding category: `inconsistency`
- Limitations:
  - The STLB-Bau catalogue is licensed by DIN and not bundled: item texts are not compared with catalogue texts, and keys are not looked up in the catalogue.
  - Keys are compared as written; two spellings of one reference are two keys.
  - One standard text can legitimately carry different unit prices; that finding is a signal for a reviewer, not an error, and carries no probability.
- References: GAEB DA XML 3.3 (2021-05): Description/STLBBau and Description/StLNo
- Parameters:
  - `key_field` (plan or profile): `standard_text_key`. Field holding the standard text key.
  - `catalogue_field` (plan or profile): `standard_text_catalog`. Field holding the key's catalogue and version.
  - `price_field` (plan or profile): `unit_price`. Field holding the unit price.
  - `max_cells_per_issue` (profile): `20`. Rows highlighted in one finding.

## llm.bill_review

**Claude bill review** (version 1.0.0). Lists what Claude named when a reviewer sent it this bill to review: the claims it rates as certain, each on the position it names, with its reason and its quote. The check itself calls no model; it reads the stored answer.

- Applies when: Bills a reviewer sent to Claude for review. The server needs an Anthropic key for that; without one nothing is sent and the check is skipped.
- Required fields: none; optional: `item_code`, `description`, `long_description`, `quantity`, `unit`, `unit_price`, `line_total`
- Evidence classes: `semantic_warning`
- Issue categories: `semantic`
- Finding category: `risk`; rule `r016`: `error`; rule `r018`: `error`; rule `r023`: `inconsistency`; rule `r031`: `ambiguity`; rule `r033`: `ambiguity`; rule `r038`: `ambiguity`; rule `r051`: `inconsistency`; rule `r082`: `inconsistency`; rule `r083`: `error`; rule `r084`: `inconsistency`; rule `r085`: `inconsistency`; rule `r112`: `error`
- Limitations:
  - A language model's suspicion, never a proof: it can name a fault that is none and miss one that is there.
  - The same bill can get other claims when it is sent again.
  - Only positions under a section heading (Titel) are read.
  - After a correction, claims on unchanged positions stay although the model has not read the changed bill.
- References: docs/evaluation/boq-practice-p1-model-review.md: the review and its claims, as measured on the practice bills

## machine_learning.near_duplicates

**Nearly identical positions in one section** (version 1.0.0). Finds positions of the same top-level section with the same unit, unit price, numbers and nearly the same quantity whose texts differ only slightly (a reordered phrase, an abbreviation, a typo) under another item code, and the line total that may be counted twice.

- Applies when: Tables that map a unit price, a unit and a description.
- Required fields: `unit_price`, `unit`, `description`; optional: `long_description`, `quantity`, `line_total`, `item_code`, `currency`
- Evidence classes: `suspected_anomaly`
- Issue categories: `duplicate`
- Finding category: `inconsistency`
- Limitations:
  - Compares positions within one top-level section of one table only.
  - Similar wording with the same numbers does not prove the same work; a bill may list similar work twice on purpose.
  - Positions with identical text are left to the rule checks; positions whose texts differ in any number are never compared.
  - The score is the text similarity, uncalibrated: not a probability of error.
- Parameters:
  - `min_similarity` (profile): `0.6`. Cosine similarity of the texts from which two positions are near copies (one swapped letter in a short text scores about 0.7: the rare misspelt word weighs much).
  - `max_quantity_difference` (profile): `0.1`. Largest relative difference of the quantities (0.10 = ±10 %).
  - `severity_near_duplicate` (profile): `medium`. Severity of a near copy.

## semantic.section_fit

**Position closer to another section** (version 1.0.0). Compares each position's text with the positions of its own section and with those of its sibling sections (same parent section) of the table, and reports a position much closer to another section than to its own.

- Applies when: Priced tables with descriptions and sections (Titel).
- Required fields: `description`; optional: `long_description`, `item_code`
- Evidence classes: `semantic_warning`
- Issue categories: `semantic`
- Finding category: `inconsistency`
- Limitations:
  - Needs section rows; tables without them are not checked.
  - Sections often hold mixed work; a position may belong where it is for reasons its text does not show.
  - Sections with fewer than the configured number of item rows are not compared.
  - The score is uncalibrated: a difference of text similarities, not a probability of error.
- References: ADR 0010: T1, a text much closer to another Titel than to its own
- Parameters:
  - `top_k` (profile): `3`. Most similar members averaged per section.
  - `min_section_size` (profile): `4`. Item rows a section needs (the row itself included) to be compared.
  - `min_similarity` (profile): `0.7`. Fit with the other section a finding needs.
  - `min_margin` (profile): `0.5`. How much better the other section must fit than the row's own.
  - `max_own_similarity` (profile): `0.5`. A row with a position at least this similar in its own section fits there and is not reported.
  - `medium_margin` (profile): `0.7`. Margin from which severity is medium.

## semantic.unit_fit

**Unit unlike similar positions** (version 1.0.0). Compares the dimension of each position's unit (length, area, volume) with that of its most similar positions by text, and reports a position whose close neighbours agree on another dimension while none shares its own.

- Applies when: Tables that map a unit and a description (bills of quantities).
- Required fields: `unit`; optional: `description`, `long_description`, `item_code`, `quantity`
- Evidence classes: `semantic_warning`
- Issue categories: `unit`
- Finding category: `inconsistency`
- Limitations:
  - Compares positions within one bill only.
  - Similar wording does not prove the same work; the same work can be measured in another unit for good reasons (a strip in m, a surface in m²).
  - Units outside the profile's vocabulary have no dimension and are not compared.
  - The score is uncalibrated: a mean text similarity, not a probability of error.
- References: ADR 0010: U1, similar positions measured in another dimension (m² against m)
- Parameters:
  - `min_similarity` (profile): `0.6`. Cosine text similarity a neighbour needs.
  - `max_neighbours` (profile): `5`. Most similar positions compared with.
  - `min_agreeing` (profile): `2`. Neighbours that must share the other dimension.
  - `min_share` (profile): `0.75`. Share of the neighbours that must share the other dimension.
  - `max_same_dimension` (profile): `0`. Neighbours in the row's own dimension that still allow a finding.
  - `compared_dimensions` (profile): `["length", "area", "volume"]`. Dimensions a finding may name, for the row and for its neighbours. Others (pieces against metres, hire per week against pieces, tonnes against cubic metres) are often measured differently on purpose; their rows still count as neighbours.
  - `medium_similarity` (profile): `0.85`. Mean similarity of the agreeing neighbours for medium severity.

## statistical.historical_price

**Historical unit price and quantity (real offers)** (version 2.2.0). Compares each priced position with similarly worded positions of the same unit in earlier priced sample offers of other projects and flags prices three times or more away from their median. Positions without such offers are compared with earlier synthetic projects, adjusting prices by a dated Destatis Ortskanäle index proxy. Reports robust log-price deviations and power-of-ten quantity deviations as review signals, never market-price evidence.

- Applies when: Positions with similarly worded history; prices assumed EUR net unless a column says otherwise.
- Required fields: `description`, `unit`, `unit_price`; optional: `long_description`, `quantity`, `price_date`, `price_tax_basis`, `currency`
- Evidence classes: `suspected_anomaly`
- Issue categories: `statistical_outlier`
- Finding category: `risk`
- Limitations:
  - Real offers: three priced sample offers, one per project and trade; few rows of other bills match their wording.
  - Real offers are offers, not awards or costs, and are not date-adjusted.
  - A project whose wording matches a fifth of the bill's rows is taken as its own.
  - Synthetic history: rates and quantities are invented, not awards, invoices or costs.
  - Similar wording is not the same scope; a reviewer judges each comparison.
  - Numbers in the compared texts must match in order; dimensions are not inferred.
  - Without a price date or bill date the comparison is wider, not dated by guess.
  - Date adjustment is an aggregate proxy, not an item-rate or regional calibration.
  - Project/supplier/site/quantity effects remain; scores are not error probabilities.
  - At least eight earlier projects by default; rows are not independent projects.
- References: tools/price_references/build_offer_history.py; samples/history/README.md; https://www.destatis.de/DE/Themen/Wirtschaft/Konjunkturindikatoren/Preise/bpr210.html
- Parameters:
  - `min_projects` (profile): `8`
  - `min_similarity` (profile): `0.65`
  - `min_log_scale` (profile): `0.23`
  - `flag_score` (profile): `2.5`
  - `min_quantity_log_scale` (profile): `0.3`
  - `quantity_flag_score` (profile): `3.5`
  - `min_quantity_ratio` (profile): `30.0`
  - `offer_ratio` (profile): `3.0`
  - `same_project_similarity` (profile): `0.95`
  - `same_project_share` (profile): `0.2`

## statistical.open_price_reference

**Unit price below a published material value** (version 1.1.0). Compares positions that name one material (reinforcing bars, steel sections, glass, plasterboard, clay bricks, bitumen membranes, PVC flooring) in that material's own unit with its average factory-gate value in Eurostat PRODCOM (German, else EU-27, 2025), and reports positions priced below the material alone, as context for review.

- Applies when: Tables that map a unit price and a unit (priced bills of quantities).
- Required fields: `unit_price`, `unit`; optional: `description`, `long_description`, `currency`
- Evidence classes: `needs_external_context`
- Issue categories: `price_reference`
- Finding category: `risk`
- Limitations:
  - Not what a position should cost: no open source publishes German installed-work prices. The reference is the material's factory-gate value only (no delivery, processing, labour, plant, overheads or profit).
  - An annual national average over every grade, size and customer of the product code; a lower price can be legitimate.
  - The reference year is past (2025) and is not indexed to the bill's date.
  - Where German figures are confidential the EU-27 average is shown, not adjusted to Germany; Eurostat rounds those totals.
  - Matches a short list of materials by keywords, only in the source's unit; every other row is counted as not compared.
  - Rows the keywords cannot match use the local model's stored suggestion when a run asked for one: a suggestion checked by code for structure and source, not for being right; it is compared only when its scope buys the material (as a floor) and a unit rule of code applies.
- References: Eurostat, Sold production, exports and imports by PRODCOM List (CPA 2.2), DS-059367; Destatis, Qualitätsbericht Produktionserhebungen 2026 (Produktionswert: Verkaufspreis ab Werk ohne Umsatzsteuer, Fracht und Rabatte)

## statistical.peer_price

**Unit price far from comparable positions** (version 1.1.0). Compares each unit price with comparable positions of the bill (similar text in the same unit, else the same unit and section, else the same unit) by a robust, leave-one-out z-score of the log price, and reports prices far from them with the amount at stake if the row were priced like them.

- Applies when: Tables that map a unit price and a unit (priced bills of quantities).
- Required fields: `unit_price`, `unit`; optional: `description`, `long_description`, `quantity`, `currency`
- Evidence classes: `suspected_anomaly`
- Issue categories: `statistical_outlier`
- Finding category: `risk`
- Limitations:
  - Compares positions within one bill only; no price history from other projects.
  - Similar wording does not prove equivalent work; comparable work can be priced differently for good reasons (quantity, access, location).
  - The score is uncalibrated: a distance in robust scales, not a probability of error.
  - Rows without a group of comparable positions are counted, not checked.
- References: Iglewicz and Hoaglin (1993), How to Detect and Handle Outliers: modified z-score
- Parameters:
  - `min_peers` (profile): `3`. Members a peer group needs.
  - `text_similarity` (profile): `0.3`. Cosine similarity a text peer needs.
  - `max_text_peers` (profile): `10`. Most similar positions used as text peers.
  - `text_band` (profile): `0.25`. Text peers are at most this much less similar than the most similar one (but at least min_peers are kept), so a group of the same work is not outvoted by looser matches (a pressure test by pipe laying, single doors by double doors).
  - `min_log_scale` (profile): `0.23`. Floor of the robust scale of log prices (0.23 ≈ ±26 %), so groups of nearly equal prices do not inflate scores.
  - `flag_score` (profile): `3.0`. |score| from which a row is reported (low severity).
  - `medium_score` (profile): `3.5`. |score| for medium severity.
  - `high_score` (profile): `6.0`. |score| for high severity.
  - `min_ratio` (profile): `1.0`. Report a row that counts toward the total only when its unit price is at least this many times above or below the group's median (1 = any score from flag_score). Prices 2 to 4 times apart are common between comparable positions of a correct bill; contingency and alternative items are reported at any ratio.
  - `peer_groups` (profile): `["text"]`. Peer groups tried in order. Only similar text by default: on the BoQ benchmark the section and unit groups found no planted price error the text group missed and tripled the signals on unplanted rows.

## statistical.quantity_factor

**Quantity a power of ten off identical positions** (version 1.0.1). Groups positions with the same text, unit and item type and reports a quantity 10, 100 or 1,000 times (or 1/10 to 1/1,000 of) the others, naming the unit slip it fits, with the amount at stake if it were measured like them.

- Applies when: Tables that map a quantity, a unit, a short text and a unit price.
- Required fields: `quantity`, `unit`, `description`, `unit_price`; optional: `currency`, `standard_text_key`, `item_type`, `discount_percent`
- Evidence classes: `suspected_anomaly`
- Issue categories: `statistical_outlier`
- Finding category: `inconsistency`
- Limitations:
  - Only positions with the same short text are compared; reworded copies are not.
  - Identical work can legitimately be measured ten times larger elsewhere; a reviewer decides.
  - A factor near another value (a slip compared with a copy of another size) is missed: only factors within the tolerance of 10, 100 or 1,000 count.
  - Items that do not count toward the totals are not compared.
- Parameters:
  - `factor_tolerance` (profile): `0.15`. Relative tolerance of the factor 10, 100 or 1,000 to the reference quantity.
  - `max_peer_ratio` (profile): `1.5`. Largest / smallest quantity the other identical positions may differ by.
  - `small_count_limit` (profile): `100`. Whole-number piece counts whose largest value is below this are not compared (1 and 10 pieces are common legitimately).
  - `unit_slips` (profile): `{"m": {"2": "cm", "3": "mm"}, "t": {"3": "kg"}, "kg": {"-3": "t"}}`. Per unit id: the exponent k of a factor 10**k between a quantity and its reference, and the unit the quantity was then probably entered in.

## statistical.rate_consistency

**Identical positions with different unit prices** (version 1.0.0). Groups positions with the same text, unit and currency (and the same standard text key when they have one) and reports unit prices that differ within a group, with the amount at stake if the position were priced like the others.

- Applies when: Tables that map a unit price, a unit and a short text.
- Required fields: `unit_price`, `unit`, `description`; optional: `quantity`, `currency`, `standard_text_key`, `discount_percent`
- Evidence classes: `suspected_anomaly`
- Issue categories: `statistical_outlier`
- Finding category: `inconsistency`
- Limitations:
  - Only positions with the same short text are compared; reworded copies are not.
  - Identical text can describe work priced differently on purpose (another building, access, timing); a reviewer decides.
  - With two different prices the bill cannot tell which one is wrong; both are shown.
  - A contingency priced differently on purpose from the position it repeats is reported too.
- References: Iglewicz and Hoaglin (1993), How to Detect and Handle Outliers: modified z-score
- Parameters:
  - `relative_tolerance` (profile): `0.01`. Relative price difference below which identical positions agree.
  - `min_log_scale` (profile): `0.005`. Floor of the robust scale of the other members' log prices, so that a group of equal prices gives a finite score.
  - `flag_score` (profile): `3.5`. |score| from which one member of a group of three or more stands out.
  - `medium_deviation` (profile): `0.2`. Relative difference from which severity is medium.
  - `compare_items_not_in_totals` (profile): `true`. Also compare items that do not count toward the totals (a contingency repeating a position is normally priced like it); findings prefer counted items as anchor.
  - `power_of_ten_tolerance` (profile): `0.02`. Relative tolerance of a factor 10, 100 or 1,000 between two prices.
