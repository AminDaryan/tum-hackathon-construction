"""``tenders.tender_for``: the tender a bid answers, among the files of the bid's project."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.dataset import Dataset
from app.services import documents, projects, tenders
from app.services.workbench import Workbench
from tests.unit.api.conftest import make_workbench

HEADER = "Item;Description;Quantity;Unit;Unit price;Total\n"
BID = "1.1;Rohr DN 250;25;m;100;2500\n1.2;Bogen 90;3;St;50;150\n1.3;Schieber DN 250;1;St;900;900\n"
TENDER = "1.1;Rohr DN 250;25;m;;\n1.2;Bogen 90;3;St;;\n1.3;Schieber DN 250;1;St;;\n"


@pytest.fixture
def workbench(tmp_path: Path) -> Workbench:
    return make_workbench(tmp_path)


def upload(wb: Workbench, name: str, rows: str, project_id: str | None = None) -> Dataset:
    document, dataset = documents.upload(
        wb, filename=name, chunks=[(HEADER + rows).encode()], profile_id="boq"
    )
    assert dataset is not None
    if project_id is not None:
        projects.membership(wb, project_id, document.document_id)
    return dataset


def test_the_unpriced_bill_of_the_bids_project_is_its_tender(workbench: Workbench) -> None:
    project = projects.create(workbench, "Ringschluss").project_id
    tender = upload(workbench, "Ausschreibung.csv", TENDER, project)
    bid = upload(workbench, "Angebot.csv", BID, project)
    found = tenders.tender_for(workbench, bid)
    assert found is not None
    assert (found.filename, found.dataset.dataset_id) == ("Ausschreibung.csv", tender.dataset_id)
    # The tender itself has no prices, so it is compared with nothing.
    assert tenders.tender_for(workbench, tender) is None


def test_a_bid_changed_in_some_positions_still_finds_its_tender(workbench: Workbench) -> None:
    project = projects.create(workbench, "Ringschluss").project_id
    upload(workbench, "Ausschreibung.csv", TENDER, project)
    changed = "1.1;Rohr DN 250;30;m;100;3000\n1.2;Bogen 90;3;St;50;150\n1.3;Schieber;1;St;9;9\n"
    assert tenders.tender_for(workbench, upload(workbench, "Angebot.csv", changed, project))


def test_no_tender_outside_the_project_or_among_priced_or_supporting_files(
    workbench: Workbench,
) -> None:
    alone = upload(workbench, "Angebot.csv", BID)
    upload(workbench, "Ausschreibung.csv", TENDER, projects.create(workbench, "Other").project_id)
    assert tenders.tender_for(workbench, alone) is None
    project = projects.create(workbench, "Ringschluss").project_id
    bid = upload(workbench, "Angebot.csv", BID, project)
    upload(workbench, "Zweites Angebot.csv", BID, project)  # priced: another bid, not a tender
    assert tenders.tender_for(workbench, bid) is None
    tender = upload(workbench, "Ausschreibung.csv", TENDER, project)
    assert tenders.tender_for(workbench, bid) is not None
    projects.move(workbench, project, tender.document_id, "support")
    assert tenders.tender_for(workbench, bid) is None


def test_a_tender_of_another_trade_with_the_same_numbers_is_not_taken(
    workbench: Workbench,
) -> None:
    project = projects.create(workbench, "Neubau").project_id
    upload(workbench, "Maler.csv", "1.1;Wand streichen;400;m2;;\n1.2;Decke;90;m2;;\n", project)
    assert tenders.tender_for(workbench, upload(workbench, "Angebot.csv", BID, project)) is None


def test_the_tender_that_matches_most_positions_wins(workbench: Workbench) -> None:
    project = projects.create(workbench, "Ringschluss").project_id
    upload(workbench, "Teil.csv", "1.1;Rohr DN 250;25;m;;\n1.2;Bogen 90;3;St;;\n", project)
    full = upload(workbench, "Ausschreibung.csv", TENDER, project)
    found = tenders.tender_for(workbench, upload(workbench, "Angebot.csv", BID, project))
    assert found is not None and found.dataset.dataset_id == full.dataset_id


def test_a_bare_price_list_matches_its_tender_by_item_number(workbench: Workbench) -> None:
    project = projects.create(workbench, "Ringschluss").project_id
    upload(workbench, "Ausschreibung.csv", TENDER, project)
    prices = upload(workbench, "Preise.csv", "1.1;;;;100;\n1.2;;;;50;\n1.3;;;;900;\n", project)
    assert tenders.tender_for(workbench, prices) is not None
