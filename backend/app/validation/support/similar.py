"""The text index of the similar-positions checks (plan contract P10).

One index per validation run over the item frame's records, cached in ``context.memo``: the
cosine similarity of TF-IDF weighted, hashed character n-grams of each position's short text and
the start of its long text. Similar wording is evidence for a comparison a reviewer can judge,
never proof that two positions are the same work.
"""

from __future__ import annotations

import zlib
from collections.abc import Sequence

import numpy as np

from app.validation.contracts.context import ValidationContext
from app.validation.support.items import ItemRecord, item_frame
from app.validation.support.text_keys import char_ngrams

TEXT_INDEX_KEY = "validation.support.text_index"
# Dimensions of the hashed n-gram vectors: enough for bills of a few thousand positions while
# keeping the similarity matrix small.
HASH_DIMENSIONS = 4096
LONG_TEXT_CHARS = 200


def similarity_matrix(records: Sequence[ItemRecord]) -> np.ndarray:
    """Cosine similarity of TF-IDF weighted, hashed character n-grams of the records' texts
    (short text and the first :data:`LONG_TEXT_CHARS` characters of the long text)."""
    grams = [
        char_ngrams(f"{r.description or ''} {(r.long_description or '')[:LONG_TEXT_CHARS]}")
        for r in records
    ]
    hashed = [[zlib.crc32(g.encode("utf-8")) % HASH_DIMENSIONS for g in gs] for gs in grams]
    counts = np.zeros((len(records), HASH_DIMENSIONS), dtype=np.float32)
    for i, buckets in enumerate(hashed):
        np.add.at(counts[i], buckets, 1.0)
    document_frequency = (counts > 0).sum(axis=0)
    idf = np.log((1 + len(records)) / (1 + document_frequency)) + 1
    weights = counts * idf.astype(np.float32)
    norms = np.linalg.norm(weights, axis=1, keepdims=True)
    weights /= np.where(norms > 0, norms, 1)
    # Annotated: numpy 2.4's stubs (Python 3.11) type this product as Any, numpy 2.5's do not.
    similarity: np.ndarray = weights @ weights.T
    return similarity


def text_index(context: ValidationContext) -> np.ndarray:
    """The similarity matrix over ``item_frame(context).records`` (row and column ``i`` for
    ``records[i]``), built on first use and cached for the run."""
    cached = context.memo.get(TEXT_INDEX_KEY)
    if isinstance(cached, np.ndarray):
        return cached
    built = similarity_matrix(item_frame(context).records)
    context.memo[TEXT_INDEX_KEY] = built
    return built
