# System requirements

Every tool and server the workbench needs, each with the one version that is tested. Use
exactly these versions. Python and npm packages are pinned by their lock files
(`backend/requirements.lock.txt`, `frontend/package-lock.json`); this file pins what the lock
files cannot.

`backend/tests/unit/test_system_requirements.py` reads the table below and fails when CI
(`.github/workflows/ci.yml`), the `Dockerfile`, `docker-compose.yml`, `backend/pyproject.toml`,
`frontend/package.json` or the lock file's header names another version. To change a version,
change it here and in the places its row names, in one commit (and update `LICENSES.md` when a
lock file changes).

## Versions

| Requirement | Version | Needed for | Pinned in |
| --- | --- | --- | --- |
| Python | 3.13.18 | the backend on Linux and macOS, in CI and in the container image | `ci.yml` (`python-version`), `Dockerfile` (`python:3.13.18-slim-trixie`) |
| Python on Windows | 3.11.9 | the backend on Windows (the last 3.11 release with a Windows installer) | `ci.yml` job `backend-windows`, `pyproject.toml` (`requires-python`, mypy and ruff target) |
| pip | 26.3 | installing the backend from the lock file | `ci.yml`, `Dockerfile`, the commands below |
| hatchling | 1.33.0 | building the backend package (`pip install -e`) | `pyproject.toml` (`[build-system]`) |
| Node.js | 24.22.3 | the web interface: build, tests, dev server | `ci.yml` (`node-version`), `Dockerfile` (`node:24.22.3-bookworm-slim`), `package.json` (its `engines` range must accept it) |
| npm | 11.19.1 | `npm ci` | comes with Node.js 24.22.3 |
| PostgreSQL | 16.16 | optional database server (SQLite is the default) | `ci.yml` (service image), `docker-compose.yml` |
| Tesseract OCR | 5.5.0 | optional: text recognition of scanned PDF bills, with German and English language data | the Debian 13 (trixie) package of the container image; elsewhere install 5.5.0 yourself |
| Ollama | 0.40.17 | optional: the local language model server (`TWB_LLM__PROVIDER=ollama`) | `docker-compose.yml` |
| Language model | qwen2.5:7b-instruct | optional: the model review; `ollama list` shows its ID as `845dbda0ea48` | `backend/app/agents/models.py` (the allow list) |

Other tools need no particular version: Git with Git LFS (the IFC demo models are LFS files,
`git lfs pull`), Docker with Compose v2 for the container image, and the Chromium build of the
browser test, which `npx playwright install chromium` takes from `@playwright/test` in the
npm lock file.

## Which Python where

The backend's `requires-python` is `>=3.11`, but only the two versions above are tested.

- **Linux and macOS: Python 3.13.18.** Not Python 3.11: the newest NumPy for Python 3.11 is
  2.4.6, and its Linux wheels (and macOS wheels before macOS 14) bundle `libquadmath`, which is
  LGPL-licensed and against the project's licence rule (no GPL, LGPL or AGPL).
  `backend/tests/unit/test_bundled_libraries.py` fails on such an installation.
- **Windows: Python 3.11.9.** NumPy 2.4.6's Windows wheel bundles the same libraries as
  NumPy 2.5.5's (OpenBLAS and the Visual C++ runtime, see `LICENSES.md`). CI tests this
  combination in the `backend-windows` job. Python 3.13.18 also installs on Windows, but CI
  does not test it there.

The lock file pins NumPy twice, with markers: 2.4.6 for Python 3.11 and 2.5.5 for 3.12 and
newer. `colorama` (a pytest dependency) is pinned for Windows only.

## Install

Backend, from `backend/`. Windows (PowerShell):

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install pip==26.3
.\.venv\Scripts\python -m pip install -c requirements.lock.txt -e ".[dev]"
```

Linux and macOS:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install pip==26.3
.venv/bin/python -m pip install -c requirements.lock.txt -e ".[dev]"
```

Add the `postgres` extra (`".[dev,postgres]"`) for the PostgreSQL driver. Frontend, from
`frontend/`, with Node.js 24.22.3 on the path: `npm ci`.
