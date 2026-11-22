"""Native libraries that installed wheels bundle must be on a documented allow-list.

Wheel repair tools copy shared libraries into the wheel: auditwheel and delvewheel into a
``<distribution>.libs/`` folder (Linux, Windows), delocate into ``<package>/.dylibs/`` (macOS).
Those libraries ship with the application, so their licences matter as much as the packages'
own. numpy 2.5.3 still bundled ``libquadmath`` (LGPL-2.1-or-later) and SciPy bundles it too;
this test fails as soon as a library outside the allow-list is installed, so an LGPL library
cannot come back unnoticed with a new version or a new dependency. The allowed libraries and
their licences are listed in ``LICENSES.md``.

A library linked statically into an extension module has no file of its own, so the folder scan
cannot see it. lxml's binary wheels link five that way and name them in their own licence file.
``LXML_STATIC_LIBRARIES`` holds that list; one test compares it with lxml's licence file and
another with the table in ``LICENSES.md``, so neither can change without the other.
"""

from __future__ import annotations

import importlib.metadata as md
import re
import sys
from pathlib import Path, PurePosixPath

import pytest

# Name prefixes (compared case-insensitively) of the bundled libraries LICENSES.md documents:
# OpenBLAS with LAPACK and the statically linked GCC runtime libgfortran (numpy), and the
# Microsoft Visual C++ runtime of the Windows wheels (numpy, pandas).
ALLOWED_PREFIXES: tuple[str, ...] = ("libscipy_openblas", "msvcp140")

# The libraries lxml's binary wheels link statically, with the licence lxml's LICENSES.txt
# gives each, as LICENSES.md documents them. GNU libiconv's LGPL 2.1 is against the project's
# licence rule; it is an open question for the owner (PROGRESS.md), not an accepted exception.
LXML_STATIC_LIBRARIES: dict[str, str] = {
    "zlib": "zlib-license",
    "iconv": "LGPL 2.1",
    "libxml2": "MIT",
    "libxslt": "MIT",
    "libexslt": "MIT",
}
_LISTED_LIBRARY = re.compile(r"^\*\*([^*]+)\*\*: *([^,\n]+)", re.MULTILINE)
LICENSES_MD = Path(__file__).resolve().parents[3] / "LICENSES.md"
# How LICENSES.md names a library of that list where it differs, and the SPDX identifier it
# gives for each licence name in lxml's file.
_DOCUMENTED_NAME = {"iconv": "GNU libiconv"}
_SPDX = {"zlib-license": "Zlib", "LGPL 2.1": "LGPL-2.1", "MIT": "MIT"}


def bundled_folder(path: PurePosixPath) -> bool:
    """Whether ``path`` (relative to site-packages) lies in a folder of bundled libraries."""
    folders = path.parts[:-1]
    return bool(folders) and (folders[0].endswith(".libs") or ".dylibs" in folders)


def is_allowed(file_name: str) -> bool:
    return file_name.casefold().startswith(ALLOWED_PREFIXES)


def bundled_libraries() -> list[tuple[str, str]]:
    """``(distribution name and version, path)`` of every file in a bundled-library folder of
    every installed distribution, from the distributions' own file lists."""
    found: list[tuple[str, str]] = []
    for distribution in md.distributions():
        for file in distribution.files or ():
            path = PurePosixPath(str(file).replace("\\", "/"))
            if bundled_folder(path):
                name = f"{distribution.metadata['Name']} {distribution.version}"
                found.append((name, path.as_posix()))
    return sorted(found)


def test_every_bundled_library_is_on_the_allow_list() -> None:
    refused = [
        f"{name}: {path}"
        for name, path in bundled_libraries()
        if not is_allowed(PurePosixPath(path).name)
    ]
    assert refused == [], (
        "Installed wheels bundle native libraries that LICENSES.md does not document; check "
        "their licences (no GPL, LGPL or AGPL) before allowing them: " + "; ".join(refused)
    )


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux wheels bundle OpenBLAS")
def test_the_scan_finds_the_library_numpy_bundles_on_linux() -> None:
    # Guards against a scan that silently finds nothing (the macOS 14 wheels use Apple's
    # Accelerate framework and bundle no library at all, so this runs on Linux only).
    numpy_files = [path for name, path in bundled_libraries() if name.startswith("numpy ")]
    assert numpy_files, "numpy's wheel bundles OpenBLAS in numpy.libs/ on Linux"
    assert all(PurePosixPath(path).name.startswith("libscipy_openblas") for path in numpy_files)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("numpy.libs/libscipy_openblas64_-4b78795a.so", True),
        ("numpy/.dylibs/libscipy_openblas64_.dylib", True),
        ("numpy.libs/msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll", True),
        ("pandas.libs/MSVCP140-A4C2229B.DLL", True),
        # What numpy 2.5.3, SciPy and scikit-learn bundle: refused.
        ("numpy.libs/libquadmath-2284e583-a9307bba.so.0.0.0", False),
        ("numpy.libs/libgfortran-83c28eba-468e71e5.so.5.0.0", False),
        ("scikit_learn.libs/libgomp-a34b3233.so.1.0.0", False),
        ("scipy/.dylibs/libgcc_s.1.1.dylib", False),
    ],
)
def test_the_allow_list_accepts_only_the_documented_libraries(path: str, expected: bool) -> None:
    location = PurePosixPath(path)
    assert bundled_folder(location)
    assert is_allowed(location.name) is expected


@pytest.mark.parametrize(
    "path",
    ["numpy/_core/_multiarray_umath.cpython-313-x86_64-linux-gnu.so", "libs/x.so", "a.libs"],
)
def test_ordinary_package_files_are_not_bundled_libraries(path: str) -> None:
    assert not bundled_folder(PurePosixPath(path))


def statically_linked(licence_text: str) -> dict[str, str]:
    """The libraries and licences that the "Binary wheels" part of lxml's LICENSES.txt lists
    (lines such as ``**zlib**: zlib-license, https://...``)."""
    _, _, wheels = licence_text.partition("Binary wheels")
    return {name: licence.strip() for name, licence in _LISTED_LIBRARY.findall(wheels)}


def test_the_libraries_lxml_links_statically_are_the_documented_ones() -> None:
    text = md.distribution("lxml").read_text("licenses/LICENSES.txt")
    assert text is not None, "lxml's wheel ships its licence file in dist-info/licenses/"
    assert statically_linked(text) == LXML_STATIC_LIBRARIES, (
        "lxml now links other libraries statically: check their licences (no GPL, LGPL or "
        "AGPL) and update LICENSES.md and LXML_STATIC_LIBRARIES"
    )


def documented_static_libraries(markdown: str) -> dict[str, str]:
    """Library and licence (the licence cell up to its first space) of each row of the
    LICENSES.md table that follows the paragraph on statically linked libraries."""
    _, _, part = markdown.partition("Libraries linked statically")
    rows: dict[str, str] = {}
    for line in part.splitlines():
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[0] == "Library" or set(cells[0]) <= {"-", ":"}:
            continue
        rows[cells[0]] = cells[2].split(" ")[0]
    return rows


def test_licenses_md_documents_the_libraries_lxml_links_statically() -> None:
    expected = {
        _DOCUMENTED_NAME.get(name, name): _SPDX[licence]
        for name, licence in LXML_STATIC_LIBRARIES.items()
    }
    assert documented_static_libraries(LICENSES_MD.read_text(encoding="utf-8")) == expected, (
        "LICENSES.md and LXML_STATIC_LIBRARIES no longer list the same statically linked "
        "libraries and licences"
    )


def test_the_documented_table_is_read_up_to_its_end() -> None:
    markdown = (
        "| a | 1 | MIT | |\n\nLibraries linked statically into a module.\n\n"
        "| Library | Version | License | Note |\n| --- | --- | --- | --- |\n"
        '| zlib | 1.3.2 | Zlib | |\n| GNU libiconv | 1.18 | LGPL-2.1 (lxml: "LGPL 2.1") | x |\n'
        "\nDevelopment only:\n\n| pytest | 9 | MIT | |\n"
    )
    assert documented_static_libraries(markdown) == {"zlib": "Zlib", "GNU libiconv": "LGPL-2.1"}


def test_the_licence_list_is_read_from_the_binary_wheel_part_only() -> None:
    text = (
        "lxml is distributed under the BSD license.\n\n**not**: a library\n\n"
        "Binary wheels\n-------------\n\n**zlib**: zlib-license, https://example.org\n\n"
        "**iconv**: LGPL 2.1, https://example.org\n\n**libxml2**: MIT\n\nExcept where...\n"
    )
    assert statically_linked(text) == {
        "zlib": "zlib-license",
        "iconv": "LGPL 2.1",
        "libxml2": "MIT",
    }
