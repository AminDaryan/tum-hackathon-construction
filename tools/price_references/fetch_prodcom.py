"""Write the PRODCOM reference values of ``statistical.open_price_reference`` from Eurostat.

Fetches only public data (Eurostat dataset DS-059367, sold production by PRODCOM code) for
Germany and the EU-27 and writes the raw value and quantity of each product code the check
maps, so the unit values it shows can be recomputed from the source. No bill data is read or
sent. From the repository root:

    python3 tools/price_references/fetch_prodcom.py > \
        backend/app/validation/statistical/data/prodcom_sold_production.json
"""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import UTC, datetime

API = "https://ec.europa.eu/eurostat/api/comext/dissemination/statistics/1.0/data/DS-059367"
INDICATORS = ("PRODVAL", "PRODQNT", "QNTUNIT", "PVALFLAG", "PQNTFLAG")
REPORTERS = ("DE", "EU27_2020")
# The codes the check maps (app/validation/statistical/open_price_reference.py, REFERENCES).
CODES = (
    "24106210",
    "24107110",
    "24107120",
    "24107130",
    "23122010",
    "23121230",
    "23121270",
    "23621050",
    "23321110",
    "23991255",
    "22241119",
)


def fetch(reporter: str) -> dict:
    query = "&".join(
        [f"reporter={reporter}", "lastTimePeriod=1"]
        + [f"indicators={i}" for i in INDICATORS]
        + [f"product={c}" for c in CODES]
    )
    with urllib.request.urlopen(f"{API}?{query}", timeout=60) as response:  # noqa: S310 fixed https URL
        return json.load(response)


def cells(data: dict) -> tuple[dict[str, dict[str, object]], dict[str, str], str, str]:
    dims, sizes = data["id"], data["size"]
    index = {d: {i: v for v, i in data["dimension"][d]["category"]["index"].items()} for d in dims}
    out: dict[str, dict[str, object]] = {}
    for position, value in data["value"].items():
        rest, coordinate = int(position), {}
        for dim, size in reversed(list(zip(dims, sizes, strict=True))):
            coordinate[dim] = index[dim][rest % size]
            rest //= size
        out.setdefault(coordinate["product"], {})[coordinate["indicators"]] = value
    labels = data["dimension"]["product"]["category"]["label"]
    [period] = data["dimension"]["time"]["category"]["index"]
    return out, labels, period, data["updated"]


def main() -> None:
    products: dict[str, dict[str, object]] = {}
    periods, updated = set(), set()
    for reporter in REPORTERS:
        values, labels, period, stamp = cells(fetch(reporter))
        periods.add(period)
        updated.add(stamp)
        for code in CODES:
            entry = products.setdefault(code, {"label": labels.get(code, "")})
            entry[reporter] = {key: values.get(code, {}).get(key) for key in INDICATORS}
    if len(periods) != 1:
        sys.exit(f"reporters returned different periods: {sorted(periods)}")
    json.dump(
        {
            "dataset": "DS-059367",
            "title": "Sold production, exports and imports by PRODCOM List (CPA 2.2)",
            "source_url": "https://ec.europa.eu/eurostat/databrowser/view/ds-059367/default/table",
            "api_url": API,
            "publisher": "Eurostat",
            "licence": (
                "Eurostat reuse policy (Commission Decision 2011/833/EU): commercial and "
                "non-commercial reuse authorised provided the source is acknowledged; "
                "https://ec.europa.eu/eurostat/help/copyright-notice"
            ),
            "reference_period": periods.pop(),
            "dataset_updated": max(updated),
            "retrieved": datetime.now(UTC).strftime("%Y-%m-%d"),
            "products": products,
        },
        sys.stdout,
        indent=2,
        ensure_ascii=False,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
