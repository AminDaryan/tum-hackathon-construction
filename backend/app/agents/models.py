"""The language models the workbench may use, with the licence and the source of their weights.

A model runs only when it is on :data:`ALLOWED_MODELS`: :func:`check_configured_model` refuses
a configured ``llm.model`` that is not, at start-up, with a message that says so. A model is
added on the project's decision once the licence of its weights is checked; only weights under
one of :data:`WEIGHT_LICENCES` can be listed. Being listed does not make a model's answers
trusted: every caller checks what the model says against the bill (see :mod:`app.risk`).

``qwen2.5:7b-instruct`` was added on 2026-11-21; its licence (Apache-2.0) was read from the
model's Ollama manifest (``ollama show --license``). Its answers are still being evaluated.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.core.config import LLMSettings
from app.core.errors import WorkbenchError

# The licences (SPDX ids) under which model weights may be used.
WEIGHT_LICENCES = frozenset({"Apache-2.0", "MIT"})


@dataclass(frozen=True, slots=True)
class AllowedModel:
    """One allowed model. ``name`` is the model as the Ollama server names it (``name:tag``),
    ``licence`` the declared licence of the weights (an SPDX id where there is one), and
    ``source`` where the weights are published."""

    name: str
    licence: str
    source: str

    def __post_init__(self) -> None:
        if self.licence not in WEIGHT_LICENCES:
            raise ValueError(
                f"model weights must be licensed under {' or '.join(sorted(WEIGHT_LICENCES))}, "
                f"not {self.licence!r}"
            )


ALLOWED_MODELS: Mapping[str, AllowedModel] = MappingProxyType(
    {
        "qwen2.5:7b-instruct": AllowedModel(
            name="qwen2.5:7b-instruct",
            licence="Apache-2.0",
            source="https://huggingface.co/Qwen/Qwen2.5-7B-Instruct, as qwen2.5:7b-instruct "
            "in the Ollama library",
        ),
    }
)


class ModelNotAllowedError(WorkbenchError):
    """The configured model is not on the allow-list (raised at start-up)."""

    code = "model_not_allowed"


def check_configured_model(
    settings: LLMSettings, allowed: Mapping[str, AllowedModel] = ALLOWED_MODELS
) -> AllowedModel | None:
    """The allow-list entry of the configured model, ``None`` when no model is configured.
    Raises :class:`ModelNotAllowedError` for a model that is not on ``allowed``."""
    if settings.model is None:
        return None
    entry = allowed.get(settings.model)
    if entry is None:
        names = ", ".join(sorted(allowed)) or "none in this version"
        raise ModelNotAllowedError(
            f"The configured language model {settings.model!r} is not on the allow-list of "
            f"models the workbench may use (allowed: {names}). Unset TWB_LLM__MODEL or choose "
            "an allowed model.",
            details={"model": settings.model, "allowed": sorted(allowed)},
        )
    return entry
