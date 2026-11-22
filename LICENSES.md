# Dependency and license inventory

Brief Part B.4: every dependency must be free, permissively licensed and self-hostable, with no
enterprise-only features of otherwise free libraries. This inventory lists every package the
locked installation contains, with the license its own package metadata declares (Python:
`License-Expression` / `License` / trove classifiers of the installed distribution; npm: the
`license` field of each package in `frontend/package-lock.json`). It was generated from the
installed environments (`backend/requirements.lock.txt` with the `dev` and `postgres` extras,
Python 3.13.18; `frontend/package-lock.json`, Node 24.22.3) and must be updated when a lock file
changes. On Windows with Python 3.11.9 (the other tested version, `SYSTEM_REQUIREMENTS.md`) the
lock installs numpy 2.4.6 instead of 2.5.5 and adds colorama; both are listed below.

No dependency calls a paid service. An optional assistant can call a hosted language model API
when its API key is set; without a key it is off, and the application works without network
access. The repository itself does not declare a project license yet; the owner chooses it.

## Backend (Python)

Runtime dependencies (`backend/pyproject.toml [project.dependencies]`) and what they pull in:

| Package | Version | License | Why |
| --- | --- | --- | --- |
| fastapi | 0.163.2 | MIT | REST API |
| starlette | 1.10.0 | BSD-3-Clause | ASGI toolkit under FastAPI |
| uvicorn | 0.54.0 | BSD-3-Clause | ASGI server |
| pydantic | 2.14.3 | MIT | typed models and validation |
| pydantic-core | 2.50.4 | MIT | pydantic's core |
| pydantic-settings | 2.16.3 | MIT | configuration from environment variables |
| python-dotenv | 1.2.4 | BSD-3-Clause | `.env` support for pydantic-settings |
| sqlalchemy | 2.1.9 | MIT | persistence (SQLite; PostgreSQL through the `postgres` extra) |
| openpyxl | 3.1.5 | MIT | XLSX reading (formulas are never evaluated) and the Excel export |
| et-xmlfile | 2.0.0 | MIT | openpyxl dependency |
| defusedxml | 0.7.1 | PSF-2.0 (Python Software Foundation License) | hardened XML parsing |
| lxml | 6.1.3 | BSD-3-Clause; its binary wheels link zlib, GNU libiconv, libxml2, libxslt and libexslt statically, see below | GAEB DA XML parsing and XSD validation |
| Tesseract OCR (system package `tesseract-ocr`, with `-deu`, `-eng` language data) | Debian package | Apache-2.0 | text recognition of scanned PDF pages; run as a separate process, installed in the Docker image |
| pypdfium2 | 5.15.2 | Apache-2.0 or BSD-3-Clause (bundles PDFium, BSD-3-Clause, and its third-party libraries under permissive licences) | PDF bills: text layer with positions |
| python-multipart | 0.0.34 | Apache-2.0 | multipart upload parsing |
| pyyaml | 6.0.3 | MIT | profile files (`safe_load` only) |
| charset-normalizer | 3.5.2 | MIT | CSV encoding detection |
| anyio | 4.16.0 | MIT | async runtime used by Starlette |
| idna | 3.20 | BSD-3-Clause | anyio dependency |
| h11 | 0.16.0 | MIT | HTTP/1.1 for uvicorn |
| click | 8.5.1 | BSD-3-Clause | uvicorn command line |
| annotated-doc | 0.0.6 | MIT | FastAPI dependency |
| annotated-types | 0.8.0 | MIT | pydantic dependency |
| typing-extensions | 4.16.0 | PSF-2.0 | typing backports |
| typing-inspection | 0.4.5 | MIT | pydantic dependency |
| opentelemetry-api | 1.45.2 | Apache-2.0 | required by this FastAPI version (API package only; no SDK or exporter is installed or configured, nothing is sent anywhere) |
| numpy | 2.5.5 (Python 3.12 and newer); 2.4.6 (Python 3.11, Windows only) | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 (both versions) | arrays for the statistics of the signal checks (floats only inside statistics; money stays `Decimal`); its wheels bundle native libraries, see below |
| pandas | 3.0.5 | BSD-3-Clause (declared as "BSD 3-Clause License") | the item frame the statistics read (`validation/support/items.py`) |
| python-dateutil | 4.0.0 | BSD-3-Clause | pandas dependency (also used by pg8000) |
| tzdata | 2026.6 | Apache-2.0 | python-dateutil dependency (IANA time zone data) |

PostgreSQL driver, optional (`[project.optional-dependencies] postgres`; installed only when
asked for: `".[postgres]"`, or the image's build argument `EXTRAS=postgres`, which
`docker-compose.yml` sets). psycopg is not used because it is LGPL-licensed.

| Package | Version | License | Why |
| --- | --- | --- | --- |
| pg8000 | 1.31.6 | BSD-3-Clause | PostgreSQL driver for SQLAlchemy (pure Python) |
| scramp | 1.5.0 | MIT-0 (MIT No Attribution; permissive, without MIT's notice condition) | SCRAM authentication for pg8000 |
| asn1crypto | 1.5.1 | MIT | scramp dependency (channel binding) |

pg8000 also needs python-dateutil, which the runtime table lists (pandas needs it too).

Hosted model, optional (`[project.optional-dependencies] llm`; installed only when asked for:
`".[llm]"`). It is used by the Claude bill review that a reviewer starts for one bill, only when
the server has its key (`TWB_BILL_REVIEW__ANTHROPIC_API_KEY`), and by `python -m
app.evaluation.llm_review --provider anthropic`, a research run of the same review against the
test bills. Both call Anthropic's paid API; the application imports the SDK only when a review is
started and works without it. Versions as
installed on 2026-11-21 (CPython 3.11, Windows); the extra is not in `requirements.lock.txt`
and not in the image. Packages the backend already lists above are not repeated.

| Package | Version | License | Why |
| --- | --- | --- | --- |
| anthropic | 2.12.0 | Apache-2.0 | Anthropic's official Python SDK, for the Claude bill review and `--provider anthropic` |
| httpx2 | 2.16.2 | BSD-3-Clause | HTTP client of the SDK |
| httpcore2 | 2.16.2 | BSD-3-Clause | Transport of httpx2 |
| truststore | 0.10.5 | MIT | Lets httpx2 use the operating system's certificate store |
| jiter | 0.19.0 | MIT | Fast JSON parsing of streamed answers |
| docstring-parser | 0.18.0 | MIT | Tool descriptions from docstrings in the SDK |
| sniffio | 1.3.1 | MIT OR Apache-2.0 | Detects the async library in use |

Native libraries bundled in the wheels. Wheel repair tools copy shared libraries into a
wheel (`<distribution>.libs/` on Linux and Windows, `<package>/.dylibs/` on macOS), so they
ship with the application. They were checked in the numpy 2.5.5 and pandas 3.0.5 wheels for
CPython 3.13 on 2026-11-20, and in the numpy 2.4.6 wheels for CPython 3.11 on 2026-11-21, and
`backend/tests/unit/test_bundled_libraries.py` fails when an installed wheel bundles a library
outside this list (allowed name prefixes: `libscipy_openblas`, `msvcp140`).

| Library | Bundled by | License | Note |
| --- | --- | --- | --- |
| `libscipy_openblas64_` (OpenBLAS) | numpy: `numpy.libs/` (Linux x86_64 and aarch64, Windows), `numpy/.dylibs/` (macOS 11 arm64) | BSD-3-Clause | the macOS 14 wheels use Apple's Accelerate framework and bundle no library |
| LAPACK, inside `libscipy_openblas64_` | numpy | BSD-3-Clause-Open-MPI | as numpy's own licence file declares |
| GCC runtime `libgfortran`, statically linked into `libscipy_openblas64_` | numpy | GPL-3.0-or-later WITH GCC-exception-3.1 | the GCC Runtime Library Exception permits distributing code compiled with GCC and linked with its runtime under the code's own terms |
| `msvcp140.dll` (Microsoft Visual C++ runtime) | numpy and pandas, Windows wheels only | Microsoft's Visual C++ redistributable terms | neither wheel's licence file lists it; never part of the Linux container image |

numpy 2.5.3 and 2.5.4 still bundled `libquadmath` (LGPL-2.1-or-later) and `libgfortran` as
separate files, so the lock file must not go below numpy 2.5.5 for Python 3.12 and newer.
numpy 2.5 needs Python 3.12; for Python 3.11 the lock pins numpy 2.4.6, which is used on Windows
only: its Windows wheel bundles the same two libraries as 2.5.5's and its licence file declares
the same statically linked GCC runtime, while its Linux wheels and its macOS 10.9 and 11
wheels still bundle `libquadmath` (and `libgfortran`, on macOS also `libgcc_s`) as separate
files; its macOS 14 wheels bundle nothing. pandas bundles nothing on
Linux and macOS. SciPy and scikit-learn are not used: SciPy's Linux wheel bundles
`libquadmath` (LGPL-2.1-or-later), and scikit-learn's bundles `libgomp`; the statistics are
written with NumPy only (ADR 0010).

Libraries linked statically into an extension module have no file of their own, so the scan
above cannot see them. The lxml binary wheels link five into their extension modules
(`lxml/etree*.so` and the others), as lxml's own `LICENSES.txt` (in its `dist-info/licenses/`)
states. The versions were read from the lxml 6.1.3 wheel for CPython 3.13 on Linux x86_64 on
2026-11-20 (`etree.LIBXML_VERSION`, `etree.LIBXSLT_VERSION`, zlib's version string and
libiconv's `_libiconv_version` in `etree*.so`). `backend/tests/unit/test_bundled_libraries.py`
compares both this table and lxml's `LICENSES.txt` with one list, so a change in what lxml
links, or in this table, fails the test.

| Library | Version | License | Note |
| --- | --- | --- | --- |
| zlib | 1.3.2 | Zlib | |
| GNU libiconv | 1.18 | LGPL-2.1 (lxml's `LICENSES.txt`: "LGPL 2.1") | **Against this project's licence rule (no GPL, LGPL or AGPL).** It came with the GAEB import and is an open question for the owner and the import's author ([PROGRESS.md](docs/handoff/PROGRESS.md#open-questions)): replace lxml, or accept the library |
| libxml2 | 2.14.6 | MIT | |
| libxslt | 1.1.43 | MIT | |
| libexslt | part of libxslt 1.1.43 | MIT | |

Development and test only (`[project.optional-dependencies] dev`):

| Package | Version | License | Why |
| --- | --- | --- | --- |
| pytest | 9.2.0 | MIT | tests |
| pluggy | 1.7.0 | MIT | pytest dependency |
| iniconfig | 2.3.1 | MIT | pytest dependency |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | pytest dependency |
| pygments | 2.21.0 | BSD-2-Clause | pytest output |
| colorama | 0.4.6 | BSD-3-Clause | pytest dependency on Windows only (coloured console output) |
| pytest-cov | 7.1.0 | MIT | coverage measurement (CI gate) |
| coverage | 7.17.3 | Apache-2.0 | pytest-cov dependency |
| httpx | 0.28.1 | BSD-3-Clause | API integration tests (test client) |
| httpcore | 1.0.9 | BSD-3-Clause | httpx dependency |
| certifi | 2026.10.23 | MPL-2.0 | CA bundle for httpx; test-only, unmodified (MPL-2.0 is a file-level copyleft license that allows use in projects under any license) |
| ruff | 0.17.5 | MIT | lint and format |
| mypy | 2.4.1 | MIT (three C files of its compiled runtime under PSF-2.0; the bundled typeshed stubs Apache-2.0 with MIT parts, all per its license files) | static type checking (`python -m mypy`, CI step "Type check") |
| mypy-extensions | 1.2.0 | MIT | mypy dependency |
| librt | 0.17.0 | MIT (with the same three PSF-2.0 C files as mypy) | mypy dependency (compiled runtime library of mypy's compiler) |
| ast-serialize | 0.13.1 | MIT | mypy dependency (compiled Python parser). Its native extension statically links the Ruff parser crates (MIT) and the 82 Rust crates its wheel's CycloneDX SBOM lists as required: each is MIT or Apache-2.0 or offers one of them as a choice, and two add a Unicode data license for their Unicode tables (unicode-ident: Unicode-3.0, unicode_names2: Unicode-DFS-2016; both permissive). The SBOM's 14 build-only crates are not linked |
| pathspec | 1.1.1 | MPL-2.0 | mypy dependency (file pattern matching); a development tool's dependency, used unmodified and never shipped, like certifi |
| pandas-stubs | 3.0.5.260914 | BSD-3-Clause | type stubs for pandas (the item frame), versioned like the pandas 3.0 series they describe |
| types-defusedxml | 0.7.0.20260504 | Apache-2.0 | type stubs for defusedxml |
| types-openpyxl | 3.1.5.20261017 | Apache-2.0 | type stubs for openpyxl |
| types-PyYAML | 6.0.12.20261113 | Apache-2.0 | type stubs for PyYAML |

## Frontend (npm)

Shipped in the browser bundle (`dependencies` and their dependencies):

| Package | Version | License |
| --- | --- | --- |
| react, react-dom | 19.3.1 | MIT |
| scheduler | 0.28.0 | MIT |
| react-router, react-router-dom | 7.18.5 | MIT |
| cookie | 1.1.1 | MIT |
| set-cookie-parser | 2.7.3 | MIT |
| prop-types | 15.8.1 | MIT |
| react-is | 16.13.1 | MIT |
| loose-envify | 1.4.0 | MIT |
| js-tokens | 4.0.0 | MIT |
| object-assign | 4.1.1 | MIT |
| lucide-react | 1.74.0 | ISC (icons) |
| pdfjs-dist | 6.5.438 | Apache-2.0 (the sheet's PDF view and its local worker) |
| @napi-rs/canvas and optional platform binaries | 1.1.1 | MIT (PDF.js optional Node canvas support; not shipped in the browser) |
| react-aria-components, react-aria (with @react-types, @internationalized) | 1.22.1, 3.53.1 | Apache-2.0 (accessible component primitives) |
| @swc/helpers | 0.5.24 | Apache-2.0 (react-aria runtime helpers) |
| aria-hidden, client-only, clsx, use-sync-external-store | 1.2.6, 0.0.1, 2.1.1, 1.7.0 | MIT (react-aria dependencies) |
| tslib | 2.9.1 | 0BSD |
| @fontsource-variable/ibm-plex-sans | 5.3.0 | OFL-1.1 (SIL Open Font License; bundling with software is permitted) |
| @fontsource/ibm-plex-mono | 5.3.0 | OFL-1.1 |

Build and test tooling (`devDependencies`, not shipped): 150 packages in the lock file. All are
MIT except: Apache-2.0 (@playwright/test, playwright and playwright-core 1.63.0, the browser
end-to-end test; aria-query, detect-libc, expect-type, xml-name-validator), BSD-2-Clause
(entities, webidl-conversions), BSD-3-Clause (source-map-js, tough-cookie), ISC (picocolors,
saxes), BlueOak-1.0.0 (graceful-fs, lru-cache; permissive), 0BSD (tslib), and MPL-2.0
(lightningcss and its platform binaries, the CSS engine of Tailwind CSS 4; build-time only,
unmodified). The Chromium build that `npx playwright install chromium` downloads for the browser
test is a test tool on the developer's or CI machine; it is not shipped or distributed.

The data grid is a project component (no AG Grid or Glide Data Grid dependency yet); if one is
added, only its free community edition may be used.

## Container image and Compose services

The `Dockerfile` adds no package beyond the lists above: it builds the interface with the
official `node:24.22.3-bookworm-slim` image (build stage only, not shipped) and runs the backend
on the official `python:3.13.18-slim-trixie` image, installing the runtime packages pinned by
`backend/requirements.lock.txt` (and the `postgres` extra when `EXTRAS=postgres`). The base image's Debian packages keep their own licenses (Debian's usual mix,
GPL tools such as the shell among them); the application does not link them and this repository
does not distribute them. The optional Compose services run unmodified upstream images as
separate processes: `postgres:16.16` (PostgreSQL License, permissive) and
`ollama/ollama:0.40.17` (MIT; reserved for a later phase, not used by this release).

## Bundled standard files

`backend/app/ingestion/gaeb/xsd/` holds unchanged XML schemas of GAEB DA XML 3.3 (release
2021-05), 3.2 (2013-10) and 3.1 (2009-12), public downloads of the Gemeinsamer Ausschuss
Elektronik im Bauwesen. The GAEB files carry no licence text. The 3.1 folder also holds the W3C
schemas that the 3.1 schemas import, as shipped in the GAEB download: `xmldsig-core-schema.xsd`
is under the W3C Software License (permissive, stated in the file); `xml.xsd`, the schema of
the XML namespace in a copy edited for GAEB, carries no licence text. Source URL and SHA-256 of
each file are in the folder's README.

## Regenerating this inventory

```bash
cd backend && .venv/bin/python - <<'EOF'
import importlib.metadata as md
for d in sorted(md.distributions(), key=lambda d: d.metadata["Name"].lower()):
    m = d.metadata
    print(m["Name"], d.version, m.get("License-Expression") or m.get("License") or
          "; ".join(c for c in (m.get_all("Classifier") or []) if c.startswith("License")))
EOF
cd ../frontend && node -e 'const l=require("./package-lock.json").packages;for(const[p,i]of Object.entries(l))if(p)console.log(p.replace(/^.*node_modules\//,""),i.version,i.license,i.dev?"dev":"")'
```
