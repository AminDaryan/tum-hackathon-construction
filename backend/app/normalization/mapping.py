"""Header -> semantic field matching and the one-to-one column assignment.

Keys are :func:`app.normalization.text.header_key`. A field is matched by its
``header_synonyms``, ``exact_header_synonyms``, label and field id (fields with
``match_headers: false`` are never matched), by these methods in priority order:

* ``header_exact``: the keys are equal (similarity 1.0);
* ``header_contains``: the synonym's words occur as a contiguous run of the header's words
  (``"unit price eur"`` contains ``"unit price"``); only synonyms of at least the profile's
  ``normalization.min_contains_chars`` (default 4) that are not exact-only (so ``me`` never
  matches ``bemerkung`` and ``preis`` never matches ``preis gp``); similarity = synonym length /
  header length;
* ``header_fuzzy``: ``difflib`` ratio of the whole keys at or above the threshold, for keys of
  at least ``normalization.min_fuzzy_chars`` (default 4) that are not exact-only (similarity =
  the ratio).

Similarity is a string-similarity measure, never a probability. Assignment is one-to-one and
greedy by (method, similarity, synonym length), then the leftmost column; when two columns tie
for a field, the field stays unmapped and the tie is reported (``column_mapping_ambiguous``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.models.dataset import ColumnMapping, MappingMethod
from app.models.profile import DomainProfile
from app.normalization.text import header_key
from app.profiles.currency import CurrencyResolver

_RANK = {
    MappingMethod.HEADER_EXACT: 3,
    MappingMethod.HEADER_CONTAINS: 2,
    MappingMethod.HEADER_FUZZY: 1,
}


@dataclass(frozen=True, slots=True)
class FieldMatch:
    field_id: str
    method: MappingMethod
    similarity: float
    synonym: str

    @property
    def score(self) -> tuple[int, float, int]:
        return (_RANK[self.method], round(self.similarity, 6), len(self.synonym))


@dataclass(slots=True)
class _FieldKeys:
    exact: dict[str, str] = field(default_factory=dict)  # key -> synonym as written
    loose: dict[str, str] = field(default_factory=dict)  # contains / fuzzy candidates


class HeaderMatcher:
    """Matches header texts against a profile's fields (memoized per header text)."""

    def __init__(
        self, profile: DomainProfile, currencies: CurrencyResolver, fuzzy_threshold: float
    ) -> None:
        self._currencies = currencies
        self._threshold = fuzzy_threshold
        self.thresholds = profile.normalization
        min_contains = self.thresholds.min_contains_chars
        self._fields: dict[str, _FieldKeys] = {}
        for definition in profile.fields:
            if not definition.match_headers:
                continue
            keys = _FieldKeys()
            exact_only = {header_key(s) for s in definition.exact_header_synonyms}
            if definition.match_headers == "exact":
                keys.exact = {header_key(s): s for s in definition.exact_header_synonyms}
                self._fields[definition.field_id] = keys
                continue
            for synonym in [
                *definition.header_synonyms,
                *definition.exact_header_synonyms,
                definition.label,
                definition.field_id,
            ]:
                key = header_key(synonym)
                if not key:
                    continue
                keys.exact.setdefault(key, synonym)
                if key not in exact_only and len(key) >= min_contains:
                    keys.loose.setdefault(key, synonym)
            self._fields[definition.field_id] = keys
        self._cache: dict[str, tuple[FieldMatch, ...]] = {}

    @property
    def has_fields(self) -> bool:
        return bool(self._fields)

    def key(self, header: str | None) -> str:
        return header_key(header, self._currencies)

    def matches(self, header: str | None) -> tuple[FieldMatch, ...]:
        """Best match per field for one header text, best first."""
        key = self.key(header)
        if not key:
            return ()
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        found: list[FieldMatch] = []
        words = f" {key} "
        for field_id, keys in self._fields.items():
            match = self._match(key, words, field_id, keys)
            if match is not None:
                found.append(match)
        result = tuple(sorted(found, key=lambda m: m.score, reverse=True))
        if len(self._cache) < 50_000:
            self._cache[key] = result
        return result

    def _match(self, key: str, words: str, field_id: str, keys: _FieldKeys) -> FieldMatch | None:
        if key in keys.exact:
            return FieldMatch(field_id, MappingMethod.HEADER_EXACT, 1.0, keys.exact[key])
        best: FieldMatch | None = None
        for synonym_key, synonym in keys.loose.items():
            if f" {synonym_key} " in words:
                candidate = FieldMatch(
                    field_id,
                    MappingMethod.HEADER_CONTAINS,
                    len(synonym_key) / len(key),
                    synonym,
                )
                if best is None or candidate.score > best.score:
                    best = candidate
        if best is not None or len(key) < self.thresholds.min_fuzzy_chars:
            return best
        for synonym_key, synonym in keys.loose.items():
            matcher = SequenceMatcher(None, key, synonym_key)
            if (
                matcher.real_quick_ratio() < self._threshold
                or matcher.quick_ratio() < self._threshold
            ):
                continue
            ratio = matcher.ratio()
            if ratio >= self._threshold:
                candidate = FieldMatch(field_id, MappingMethod.HEADER_FUZZY, ratio, synonym)
                if best is None or candidate.score > best.score:
                    best = candidate
        return best

    def fields_matched(self, headers: Iterable[str | None]) -> set[str]:
        """Distinct fields any of ``headers`` matches (header row detection score)."""
        return {match.field_id for header in headers for match in self.matches(header)}


@dataclass(frozen=True, slots=True)
class Assignment:
    mappings: dict[int, ColumnMapping]  # source column -> mapping
    ambiguous: list[tuple[str, list[int]]]  # field id -> tied source columns


def assign_fields(
    candidates: dict[int, tuple[FieldMatch, ...]],
    *,
    user: dict[int, str | None] | None = None,
) -> Assignment:
    """One-to-one assignment. ``candidates`` maps source columns to their matches; ``user``
    holds reviewer decisions (source column -> field id, or ``None`` = unmapped), which win."""
    user = user or {}
    mappings: dict[int, ColumnMapping] = {
        column: ColumnMapping(field_id=field_id, method=MappingMethod.USER)
        for column, field_id in user.items()
        if field_id is not None
    }
    taken_fields = {m.field_id for m in mappings.values()}
    pairs = [
        (column, match)
        for column, matches in candidates.items()
        if column not in user
        for match in matches
        if match.field_id not in taken_fields
    ]
    pairs.sort(key=lambda p: (tuple(-v for v in p[1].score), p[0]))
    by_field: dict[str, list[tuple[int, FieldMatch]]] = {}
    for column, match in pairs:
        by_field.setdefault(match.field_id, []).append((column, match))
    blocked: set[str] = set()
    ambiguous: list[tuple[str, list[int]]] = []
    for column, match in pairs:
        if column in mappings or match.field_id in taken_fields or match.field_id in blocked:
            continue
        rivals = [
            other
            for other, other_match in by_field[match.field_id]
            if other != column and other not in mappings and other_match.score == match.score
        ]
        if rivals:
            blocked.add(match.field_id)
            ambiguous.append((match.field_id, sorted([column, *rivals])))
            continue
        mappings[column] = ColumnMapping(
            field_id=match.field_id,
            method=match.method,
            matched_synonym=match.synonym,
            similarity=round(match.similarity, 4),
        )
        taken_fields.add(match.field_id)
    return Assignment(mappings, ambiguous)
