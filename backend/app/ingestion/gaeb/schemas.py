"""The GAEB DA XML versions and exchange phases the workbench reads, and their official schemas.

One entry per (version, phase). Supporting another version or phase means adding its unchanged
XSD files under ``xsd/<version>/`` and one entry here; nothing outside this package changes.
Each schema file is pinned by SHA-256 and compiled offline: a changed file is refused, and no
schema is ever fetched from the network.

Versions 3.2 and 3.3 name the phase in the namespace (``.../DA83/3.3``). Version 3.1 uses one
namespace for every phase (``.../GAEB_DA_XML/200407``); there the phase is ``Award/DP``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from lxml import etree

from app.core.errors import ExtractionError

XSD_DIR = Path(__file__).parent / "xsd"
NAMESPACE_PATTERN = re.compile(r"^http://www\.gaeb\.de/GAEB_DA_XML/DA(\d{2})/(\d+\.\d+)$")
NAMESPACE_31 = "http://www.gaeb.de/GAEB_DA_XML/200407"


@dataclass(frozen=True, slots=True)
class GaebSchema:
    version: str  # "3.3"
    phase: str  # exchange phase, "83"
    dp_values: frozenset[str]  # values Award/DP may take in this phase
    namespace: str
    release: str  # schema release date, for messages
    # (file name, SHA-256) of every file the phase schema needs; the first is compiled, the
    # others are the files it redefines or imports.
    files: tuple[tuple[str, str], ...]

    @property
    def xsd(self) -> str:
        return self.files[0][0]

    @property
    def sha256(self) -> str:
        return self.files[0][1]

    @property
    def label(self) -> str:
        return f"GAEB DA XML {self.version} ({self.release}) X{self.phase}"


def _phase_namespace(phase: str, version: str) -> str:
    return f"http://www.gaeb.de/GAEB_DA_XML/DA{phase}/{version}"


_LIB_33 = (
    "GAEB_DA_XML_Lib_3.3_2021-05.xsd",
    "a00cad3a5bfaf079de936393c0827c2387d4b9407c113359cca4b493903388ec",
)
_LIB_32 = (
    "GAEB_DA_XML_Lib_3.2_2013-10.xsd",
    "f8d736e96f3f2e1ba6e97aa0492dedad1c2064fafc502a7f70466b34b67d1f77",
)
# Imported by both 3.1 schemas (W3C schemas for xml:lang and XML signatures).
_W3C_31 = (
    ("xml.xsd", "068d7ed95badc1ccf1be78b47e97a3ad9f7d10e17d3d3d684606e62a85de20ed"),
    (
        "xmldsig-core-schema.xsd",
        "af234e51dee3dbc3be288c79abdca95208e228f400259c8a485099bfb75eb88f",
    ),
)
_ALL_31 = (  # X81 to X83 and X85 to X87 share one schema in 3.1
    "GAEB_DA_XML 3.1 2009-12.xsd",
    "4baa2b88e489ca9797ad63e8e6ee5af6fd2d93a312bd9b9a8b6ad660a48438c3",
)
_X84_31 = (
    "GAEB_DA_XML_84 3.1 2009-12.xsd",
    "f26d50c58c478fd7599c2a1f87a5d30451dce538ced3a4292c05e4e4200611de",
)


def _v33(phase: str, sha256: str, dp_values: frozenset[str] | None = None) -> GaebSchema:
    return GaebSchema(
        "3.3",
        phase,
        dp_values or frozenset({phase}),
        _phase_namespace(phase, "3.3"),
        "2021-05",
        ((f"GAEB_DA_XML_{phase}_3.3_2021-05.xsd", sha256), _LIB_33),
    )


def _v32(phase: str, sha256: str) -> GaebSchema:
    return GaebSchema(
        "3.2",
        phase,
        frozenset({phase}),
        _phase_namespace(phase, "3.2"),
        "2013-10",
        ((f"GAEB_DA_XML_{phase}_3.2_2013-10.xsd", sha256), _LIB_32),
    )


def _v31(phase: str) -> GaebSchema:
    main = _X84_31 if phase == "84" else _ALL_31
    return GaebSchema("3.1", phase, frozenset({phase}), NAMESPACE_31, "2009-12", (main, *_W3C_31))


SCHEMAS: tuple[GaebSchema, ...] = (
    _v33("81", "aa24ed698088308d38f1ff7612643e55e70a847f6b5d433aa10dcd6dfe6c3ea3"),
    _v33("83", "a963ca5b6a93ee0f7a83d3138272a4116635e30e7b288c6ba8761ed444cabaa8"),
    _v33(
        "84",
        "67282b688db3bb12a4ded22c7b677e30ce105f9d1f80d02d084be67156e1cc42",
        frozenset({"84", "84Z"}),
    ),
    _v33("86", "334853ca68fe07c1321880c40f27b776c8133ec8c34207c63b0d438ab6e45e0d"),
    _v32("81", "655f8a49716efd7186f6598c29b5208032060f57bc7f251c68d895ff0a7213f5"),
    _v32("83", "51bcd0cc37c7851dbb89520d8a6663b9fcaa9982575476410432e346132c8f6e"),
    _v32("84", "c57677b3b8be38371dabc9a83781049be483f0bd99eb9b771851ea9a6959ea5e"),
    _v32("86", "41e4da0a21f4164e625d867f5c0dc5a5c49be3075689668ee3e364b95cf75706"),
    _v31("81"),
    _v31("83"),
    _v31("84"),
    _v31("86"),
)
PHASES: tuple[str, ...] = tuple(sorted({s.phase for s in SCHEMAS}))
VERSIONS: tuple[str, ...] = tuple(sorted({s.version for s in SCHEMAS}))


def schemas_for(namespace: str) -> list[GaebSchema]:
    """The supported schemas whose namespace is exactly ``namespace`` (one per phase)."""
    return [s for s in SCHEMAS if s.namespace == namespace]


@cache
def compiled(schema: GaebSchema) -> etree.XMLSchema:
    """The official XSD of ``schema``, hash-checked and compiled once per process."""
    folder = XSD_DIR / schema.version
    for name, expected in schema.files:
        actual = hashlib.sha256((folder / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ExtractionError(
                f"The bundled schema {name} has changed (SHA-256 {actual[:12]}…); it must be the "
                "unchanged official file.",
                details={"reason": "schema_hash_mismatch", "schema": name},
            )
    # The W3C signature schema that 3.1 imports declares a DOCTYPE; its DTD is never loaded
    # and no entity is resolved, as for the uploaded files.
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    document = etree.parse(str(folder / schema.xsd), parser)
    return etree.XMLSchema(document)
