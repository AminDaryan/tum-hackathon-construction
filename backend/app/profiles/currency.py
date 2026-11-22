"""Currency marker recognition shared by normalization and the currency detector.

Only explicit markers count as evidence: a symbol or code written in the cell, a currency in a
column header, an Excel number format, or a dedicated currency column. An unmarked amount is
"unknown currency", never assumed to be the default currency.

Which tokens name which currency is data, not code: the vocabulary in
``app/profiles/data/currencies.yaml`` (:data:`VOCABULARY_FILE`) is loaded for every profile,
and a domain profile adds or overrides aliases with ``currency_aliases``. Ambiguous symbols
(the vocabulary's ``ambiguous_symbols``) are not guessed: they mark a currency without
deciding it, and in an Excel number format they resolve only when its locale tag names the
country; built-in formats with a bare symbol carry no locale and stay unknown.
"""

from __future__ import annotations

import re
import unicodedata
from functools import cache
from pathlib import Path

import yaml
from pydantic import Field, ValidationError, field_validator, model_validator

from app.core.errors import ProfileError
from app.models.base import FrozenModel
from app.models.profile import DomainProfile

VOCABULARY_FILE = Path(__file__).resolve().parent / "data" / "currencies.yaml"

_ISO_CODE = re.compile(r"[A-Z]{3}")
_LOCALE_ID = re.compile(r"[1-9a-f][0-9a-f]{0,7}")
# A word marker in free text: 2-5 letters, optional trailing dot, not part of a longer word.
_TEXT_WORD = r"(?<![^\W\d_])(?:[^\W\d_]{2,5}\.?)(?![^\W\d_])"
# A word marker attached to number text, before or after it.
_NUMBER_WORD = r"[^\W\d_]{2,5}\.?"
# Excel locale-tagged currency formats: [$<symbol or code>] with an optional -<locale id>.
_EXCEL_CURRENCY_TAG = re.compile(r"\[\$([^\]-]*)(?:-([0-9A-Fa-f]+))?\]")
_QUOTED_LITERAL = re.compile(r'"([^"]+)"')
_BRACKETED = re.compile(r"\[[^\]]*\]")

# Excel limits number formats to 255 characters; longer text is not a format we interpret.
MAX_NUMBER_FORMAT_CHARS = 255


def token_key(token: str) -> str:
    """Comparison key of a currency token: NFKC, outer whitespace removed, case folded."""
    return unicodedata.normalize("NFKC", token).strip().casefold()


class CurrencyVocabulary(FrozenModel):
    """Which written tokens name which ISO 4217 currency (see :data:`VOCABULARY_FILE`).

    ``aliases``: token -> code. ``symbols``: tokens recognized in free text and next to
    numbers besides 2-5 letter words. ``ambiguous_symbols``: symbols of several currencies,
    never resolved from text. ``locale_currencies``: Windows locale id (hex) of an Excel
    currency tag -> what an ambiguous symbol means there. ``number_format_symbols``: aliases
    that mark a number format's currency wherever they stand in it, in order."""

    aliases: dict[str, str] = Field(min_length=1)
    symbols: list[str] = Field(default_factory=list)
    ambiguous_symbols: list[str] = Field(default_factory=list)
    locale_currencies: dict[str, str] = Field(default_factory=dict)
    number_format_symbols: list[str] = Field(default_factory=list)

    @field_validator("aliases", "locale_currencies")
    @classmethod
    def _iso_targets(cls, value: dict[str, str]) -> dict[str, str]:
        bad = sorted(code for code in value.values() if not _ISO_CODE.fullmatch(code))
        if bad:
            raise ValueError(f"Not ISO 4217 codes: {bad}")
        return value

    @field_validator("aliases")
    @classmethod
    def _normalized_aliases(cls, value: dict[str, str]) -> dict[str, str]:
        keys = [token_key(alias) for alias in value]
        if not all(keys) or len(set(keys)) != len(keys):
            raise ValueError("Aliases must be non-empty and distinct after normalization")
        return dict(zip(keys, value.values(), strict=True))

    @field_validator("symbols", "ambiguous_symbols")
    @classmethod
    def _normalized_symbols(cls, value: list[str]) -> list[str]:
        keys = [token_key(symbol) for symbol in value]
        if not all(keys) or len(set(keys)) != len(keys):
            raise ValueError("Symbols must be non-empty and distinct after normalization")
        return keys

    @field_validator("locale_currencies")
    @classmethod
    def _locale_ids(cls, value: dict[str, str]) -> dict[str, str]:
        bad = sorted(key for key in value if not _LOCALE_ID.fullmatch(key))
        if bad:
            raise ValueError(f"Locale ids must be lower-case hex without leading zeros: {bad}")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> CurrencyVocabulary:
        resolvable = sorted(set(self.ambiguous_symbols) & set(self.aliases))
        if resolvable:
            raise ValueError(f"Ambiguous symbols must not be aliases: {resolvable}")
        # A symbol that names no currency would make every number written with it unreadable.
        known = set(self.aliases) | set(self.ambiguous_symbols)
        unresolved = [symbol for symbol in self.symbols if symbol not in known]
        if unresolved:
            raise ValueError(f"Symbols must be aliases or ambiguous symbols: {unresolved}")
        unknown = [s for s in self.number_format_symbols if token_key(s) not in self.aliases]
        if unknown:
            raise ValueError(f"number_format_symbols must be aliases: {unknown}")
        return self


def load_vocabulary(path: Path) -> CurrencyVocabulary:
    """Parse a currency vocabulary file (``yaml.safe_load``); :class:`ProfileError` names the
    file on any problem."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ProfileError(f"Cannot read currency vocabulary {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileError(f"Currency vocabulary {path.name} must contain a mapping")
    try:
        return CurrencyVocabulary.model_validate(data)
    except ValidationError as exc:
        raise ProfileError(
            f"Currency vocabulary {path.name} is invalid",
            details={"errors": exc.errors(include_url=False, include_context=False)},
        ) from exc


@cache
def default_vocabulary() -> CurrencyVocabulary:
    """The shipped vocabulary, read and validated once per process."""
    return load_vocabulary(VOCABULARY_FILE)


class CurrencyResolver:
    """Currency lookups for one profile: the vocabulary's aliases plus the profile's own."""

    def __init__(
        self,
        extra_aliases: dict[str, str] | None = None,
        *,
        vocabulary: CurrencyVocabulary | None = None,
    ) -> None:
        self._vocabulary = vocabulary or default_vocabulary()
        self._aliases = dict(self._vocabulary.aliases)
        for alias, code in (extra_aliases or {}).items():
            self._aliases[alias.casefold()] = code
        self._symbols = frozenset(self._vocabulary.symbols)
        self._ambiguous = frozenset(self._vocabulary.ambiguous_symbols)
        longest_first = sorted(self._vocabulary.symbols, key=lambda s: (-len(s), s))
        symbols = "".join(f"{re.escape(symbol)}|" for symbol in longest_first)
        self._token = re.compile(f"{symbols}{_TEXT_WORD}", re.IGNORECASE)
        # One marker directly before or after number text (compared as written).
        self.leading_marker: re.Pattern[str] = re.compile(rf"^({symbols}{_NUMBER_WORD})\s*")
        self.trailing_marker: re.Pattern[str] = re.compile(rf"\s*({symbols}{_NUMBER_WORD})$")
        # Number formats repeat across thousands of cells: one resolution per distinct format.
        self._format_cache: dict[str, str | None] = {}

    @classmethod
    def from_profile(cls, profile: DomainProfile) -> CurrencyResolver:
        return cls(profile.currency_aliases)

    def resolve_token(self, token: str) -> str | None:
        """ISO code for a single marker such as a symbol, a code or a currency name."""
        return self._aliases.get(token_key(token))

    def is_symbol(self, text: str) -> bool:
        """True when ``text`` is one of the vocabulary's symbols (resolvable or ambiguous)."""
        return token_key(text) in self._symbols

    def is_ambiguous(self, token: str) -> bool:
        """True for a symbol that stands for several currencies (never resolved from text)."""
        return token_key(token) in self._ambiguous

    def find_in_text(self, text: str | None) -> set[str]:
        """All currency codes explicitly marked in free text (e.g. a bracketed header unit)."""
        if not text:
            return set()
        found = set()
        for match in self._token.finditer(unicodedata.normalize("NFKC", text)):
            code = self.resolve_token(match.group(0))
            if code:
                found.add(code)
        return found

    def find_in_number_format(self, number_format: str | None) -> str | None:
        """Currency declared by an Excel number format, if any (memoized per resolver;
        formats longer than :data:`MAX_NUMBER_FORMAT_CHARS` are not interpreted)."""
        if not number_format or len(number_format) > MAX_NUMBER_FORMAT_CHARS:
            return None
        if number_format in self._format_cache:
            return self._format_cache[number_format]
        if len(self._format_cache) >= 4096:
            self._format_cache.clear()
        code = self._resolve_number_format(number_format)
        self._format_cache[number_format] = code
        return code

    def _resolve_number_format(self, number_format: str) -> str | None:
        tag = _EXCEL_CURRENCY_TAG.search(number_format)
        if tag:
            locale_id = (tag.group(2) or "").lstrip("0").casefold()
            if self.is_ambiguous(tag.group(1)):
                return self._vocabulary.locale_currencies.get(locale_id)
            code = self.resolve_token(tag.group(1))
            if code:
                return code
        # Quoted literals: a marker in quotes before or after the number pattern.
        for literal in _QUOTED_LITERAL.findall(number_format):
            codes = self.find_in_text(literal)
            if len(codes) == 1:
                return codes.pop()
        without_tags = _BRACKETED.sub("", number_format)
        for symbol in self._vocabulary.number_format_symbols:
            if symbol in without_tags:
                return self._aliases[token_key(symbol)]
        return None
