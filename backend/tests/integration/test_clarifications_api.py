"""A project's clarifications and decision cutoff through the real API and on-disk database."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.risk import service as risk_service
from app.services import projects
from tests.integration.test_api import _csv, _workbench
from tests.integration.test_api import _upload as upload
from tests.integration.test_risk_api import ROWS

API = "/api/v1"
BILL = "Item;Description;Quantity;Unit;Unit price;Total\n1;Pipe;10;m;7;70\n"


def _raised(listing: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in listing["items"] if item["clarification_id"]]


def _suggested(listing: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in listing["items"] if item["clarification_id"] is None]


def _upload(client: TestClient, name: str) -> str:
    response = client.post(API + "/documents", files={"file": (name, BILL)})
    assert response.status_code == 201, response.text
    return str(response.json()["document"]["document_id"])


def test_clarifications_are_raised_once_changed_and_kept(tmp_path: Path) -> None:
    wb = _workbench(tmp_path, sqlite=True)
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        project = client.post(API + "/projects", json={"name": "Tender A"}).json()
        url = API + f"/projects/{project['project_id']}"
        bill, outside = _upload(client, "bill.csv"), _upload(client, "other.csv")
        assert client.put(url + "/documents", json={"document_id": bill}).status_code == 200
        listing = url + "/clarifications"
        assert client.get(listing).json() == {"items": [], "total": 0, "offset": 0, "limit": 10}

        new = {
            "document_id": bill,
            "risk_id": "risk_0123456789abcdef",
            "tier": "high",
            "title": "  Rock layer in the anchor zone: drilling method?  ",
        }
        raised = client.post(listing, json=new)
        assert raised.status_code == 201, raised.text
        first = raised.json()
        assert first["title"] == "Rock layer in the anchor zone: drilling method?"
        assert (first["kind"], first["status"], first["phase"]) == (
            "bidder_question",
            "draft",
            "bid",
        )
        assert (first["due"], first["answer"]) == (None, "")
        assert (first["project_id"], first["tier"]) == (project["project_id"], "high")
        # Asking again adds nothing while the first is undecided; another party is a second one.
        again = client.post(listing, json=new)
        assert (again.status_code, again.json()) == (200, first)
        assert first["sent_at"] is None
        price = {**new, "kind": "subcontractor", "title": "Rock drilling price, 200 anchors"}
        # Raised as sent, it is sent now.
        sent = client.post(listing, json={**price, "status": "sent"})
        assert sent.status_code == 201 and sent.json()["sent_at"] is not None
        kinds = [item["kind"] for item in client.get(listing).json()["items"]]
        assert kinds == ["bidder_question", "subcontractor"]

        one = API + f"/clarifications/{first['clarification_id']}"
        decided = client.put(
            one,
            json={
                "kind": "bidder_question",
                "title": "Drilling method in the anchor zone",
                "status": "decided",
                "due": "2026-12-03",
                "phase": "after_award",
                "answer": "Rotary drilling, priced in position 1.",
            },
        )
        assert decided.status_code == 200, decided.text
        changed = decided.json()
        assert (changed["status"], changed["due"], changed["phase"]) == (
            "decided",
            "2026-12-03",
            "after_award",
        )
        assert changed["answer"] == "Rotary drilling, priced in position 1."
        # What a reviewer cannot set stays: the reminder, its tier and when it was raised.
        for kept in ("clarification_id", "document_id", "risk_id", "tier", "created_at"):
            assert changed[kept] == first[kept], kept
        # Once decided, the same reminder can be asked about again.
        assert client.post(listing, json=new).status_code == 201
        # A PUT replaces all a reviewer sets: what it leaves out goes back to its default.
        reset = client.put(one, json={"title": "Drilling method"}).json()
        assert (reset["status"], reset["due"], reset["phase"], reset["answer"]) == (
            "draft",
            None,
            "bid",
            "",
        )

        for bad in (
            {**new, "document_id": outside},  # a file of no bill of this project
            {**new, "tier": "huge"},
            {**new, "kind": "client"},
            {**new, "title": "   "},
            {**new, "project_id": "prj_other"},
        ):
            assert client.post(listing, json=bad).status_code == 422, bad
        assert client.put(one, json={"title": "X", "status": "finished"}).status_code == 422
        assert client.put(one, json={"title": "X", "due": "soon"}).status_code == 422
        assert client.get(API + "/projects/prj_missing/clarifications").status_code == 404
        assert (
            client.post(API + "/projects/prj_missing/clarifications", json=new).status_code == 404
        )
        assert (
            client.put(API + "/clarifications/clr_missing", json={"title": "X"}).status_code == 404
        )

        # The day of the bid decision: set, left as it is by other changes, cleared by null.
        assert client.get(url).json()["project"]["decision_cutoff"] is None
        assert client.patch(url, json={"decision_cutoff": "soon"}).status_code == 422
        cutoff = client.patch(url, json={"decision_cutoff": "2026-12-03"})
        assert cutoff.status_code == 200, cutoff.text
        assert cutoff.json()["decision_cutoff"] == "2026-12-03"
        assert (
            client.patch(url, json={"name": "Tender B"}).json()["decision_cutoff"] == "2026-12-03"
        )
        assert client.patch(url, json={"decision_cutoff": None}).json()["decision_cutoff"] is None
        assert client.patch(url, json={"decision_cutoff": "2026-12-04"}).status_code == 200
    wb.close()
    # Reopen the on-disk database, not just another connection or app with the same objects.
    restarted = _workbench(tmp_path, sqlite=True)
    with TestClient(create_app(workbench=restarted), base_url="http://localhost") as client:
        kept = client.get(listing).json()["items"]
        assert len(kept) == 3 and kept[0] == reset
        assert kept[1]["kind"] == "subcontractor"
        assert client.get(url).json()["project"]["decision_cutoff"] == "2026-12-04"
    restarted.close()


def test_clarifications_need_the_sql_database_and_the_cutoff_does_not(tmp_path: Path) -> None:
    wb = _workbench(tmp_path)  # in-memory repositories
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        project = client.post(API + "/projects", json={"name": "Tender A"}).json()
        url = API + f"/projects/{project['project_id']}"
        refused = client.get(url + "/clarifications")
        assert refused.status_code == 422
        assert "SQL persistence" in refused.json()["error"]["message"]
        patched = client.patch(url, json={"decision_cutoff": "2026-12-03"}).json()
        assert patched["decision_cutoff"] == "2026-12-03"
    wb.close()


def test_the_questions_of_a_validated_project_are_listed_until_raised(tmp_path: Path) -> None:
    wb = _workbench(tmp_path, sqlite=True)
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        project = client.post(API + "/projects", json={"name": "Tender"}).json()
        url = API + f"/projects/{project['project_id']}"
        bill = upload(client, _csv(ROWS), "Rohbau.csv").json()["document"]["document_id"]
        client.put(url + "/documents", json={"document_id": bill})
        listing = url + "/clarifications"
        # Not validated yet: nothing to ask.
        assert client.get(listing).json() == {"items": [], "total": 0, "offset": 0, "limit": 10}
        assert client.post(url + "/validation").status_code == 202
        wb.jobs.shutdown()  # wait for the real validation

        suggested = _suggested(client.get(listing, params={"limit": 100}).json())
        assert suggested, "the synthetic bill asks the client at least one question"
        run_id = client.get(url).json()["project"]["validation"]["runs"][bill]
        report = client.get(API + f"/validation-runs/{run_id}/risks").json()
        asking = {r["risk_id"]: r for r in report["risks"] if r["question"]}
        assert [s["risk_id"] for s in suggested] == list(asking)
        first = suggested[0]
        assert first["document_id"] == bill
        assert (first["title"], first["tier"]) == (
            asking[first["risk_id"]]["question"],
            asking[first["risk_id"]]["tier"],
        )

        # Raised, it is a clarification and no longer a suggestion.
        raised = client.post(
            listing, json={k: first[k] for k in ("document_id", "risk_id", "tier", "title")}
        )
        assert raised.status_code == 201, raised.text
        after = client.get(listing, params={"limit": 100}).json()
        assert [item["risk_id"] for item in _raised(after)] == [first["risk_id"]]
        assert first["risk_id"] not in {s["risk_id"] for s in _suggested(after)}
        assert len(_suggested(after)) == len(suggested) - 1


def test_an_email_about_a_risk_is_listed_as_a_draft_then_sent(tmp_path: Path) -> None:
    wb = _workbench(tmp_path, sqlite=True)
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        project = client.post(API + "/projects", json={"name": "Tender A"}).json()
        url = API + f"/projects/{project['project_id']}"
        bill, outside = _upload(client, "bill.csv"), _upload(client, "other.csv")
        assert client.put(url + "/documents", json={"document_id": bill}).status_code == 200
        risk = {"document_id": bill, "risk_id": "risk_rock", "tier": "high"}
        # Another party already asked about the same risk: the email does not touch it.
        price = {**risk, "kind": "subcontractor", "title": "Rock drilling price"}
        subcontractor = client.post(url + "/clarifications", json=price).json()
        emails = url + "/clarifications/emails"
        email = {
            **risk,
            "title": "Rock layer in the anchor zone",
            "issue_id": "iss_1",
            "subject": "Question on the bill: rock layer",
            "body": "Hello, which drilling method?",
        }
        drafted = client.post(emails, json=email)
        assert drafted.status_code == 200, drafted.text
        draft = drafted.json()
        assert (draft["kind"], draft["status"], draft["sent_at"], draft["recipient"]) == (
            "bidder_question",
            "draft",
            None,
            None,
        )
        assert (draft["issue_id"], draft["subject"], draft["body"]) == (
            "iss_1",
            "Question on the bill: rock layer",
            "Hello, which drilling method?",
        )
        # Opened in the email app with the edits made there: the same clarification, sent.
        edited = {**email, "recipient": " client@example.com ", "body": "Edited.", "sent": True}
        sent = client.post(emails, json=edited).json()
        assert sent["clarification_id"] == draft["clarification_id"]
        assert (sent["status"], sent["recipient"], sent["body"]) == (
            "sent",
            "client@example.com",
            "Edited.",
        )
        assert sent["sent_at"] is not None
        # Copied again later: still the first time it was sent, the recipient kept.
        again = client.post(emails, json={**email, "sent": True}).json()
        assert (again["sent_at"], again["recipient"]) == (sent["sent_at"], "client@example.com")
        listed = client.get(url + "/clarifications").json()["items"]
        assert [(i["kind"], i["status"]) for i in listed] == [
            ("subcontractor", "draft"),
            ("bidder_question", "sent"),
        ]
        assert listed[0] == subcontractor

        # The status moves on in the list; the email and its sent time stay.
        one = API + f"/clarifications/{sent['clarification_id']}"
        answered = client.put(one, json={"title": sent["title"], "status": "answered"}).json()
        assert (answered["status"], answered["sent_at"], answered["subject"]) == (
            "answered",
            sent["sent_at"],
            "Question on the bill: rock layer",
        )
        # Set to sent by hand, a clarification without an email is sent from then.
        other = API + f"/clarifications/{subcontractor['clarification_id']}"
        by_hand = client.put(other, json={"title": "Rock drilling price", "status": "sent"})
        assert by_hand.json()["sent_at"] is not None

        assert client.post(emails, json={**email, "document_id": outside}).status_code == 422
        assert client.post(emails, json={**email, "title": " "}).status_code == 422
    wb.close()


def test_reading_new_arithmetic_questions_keeps_saved_edits_and_review_decisions(
    tmp_path: Path,
) -> None:
    # Old drafts are user data, not generated replacements.
    wb = _workbench(tmp_path, sqlite=True)
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        project = client.post(API + "/projects", json={"name": "Synthetic confirmation"}).json()
        url = API + f"/projects/{project['project_id']}"
        document = upload(client, _csv(ROWS), "arithmetic-review.csv").json()["document"]
        client.put(url + "/documents", json={"document_id": document["document_id"]})
        assert client.post(url + "/validation").status_code == 202
        wb.jobs.shutdown()
        run_id = client.get(url).json()["project"]["validation"]["runs"][document["document_id"]]
        risks_url = API + f"/validation-runs/{run_id}/risks"
        first = client.get(risks_url).json()
        arithmetic = next(r for r in first["risks"] if r["risk_type"] == "R076")
        assert arithmetic["question"] and "confirm" in arithmetic["question"].lower()
        draft = {
            "document_id": document["document_id"],
            "risk_id": arithmetic["risk_id"],
            "tier": arithmetic["tier"],
            "title": "My edited old clarification",
            "subject": "Previously saved subject",
            "body": "Please use the wording I reviewed.",
        }
        saved = client.post(url + "/clarifications/emails", json=draft)
        assert saved.status_code == 200, saved.text
        review_url = API + f"/validation-runs/{run_id}/risk-reviews"
        decision = client.put(
            review_url + "/" + arithmetic["risk_id"], json={"status": "in_review"}
        )
        assert decision.status_code == 200, decision.text
        for path in (risks_url, url + "/risk-report", url + "/risk-report/pdf"):
            assert client.get(path).status_code == 200
        listed = client.get(url + "/clarifications", params={"limit": 100}).json()
        assert _raised(listed) == [saved.json()]
        assert arithmetic["risk_id"] not in {s["risk_id"] for s in _suggested(listed)}
        [review] = client.get(review_url).json()["items"]
        assert review["risk_id"] == arithmetic["risk_id"] and review["status"] == "in_review"
    wb.close()
    restarted = _workbench(tmp_path, sqlite=True)
    with TestClient(create_app(workbench=restarted), base_url="http://localhost") as client:
        listed = client.get(url + "/clarifications", params={"limit": 100}).json()
        assert _raised(listed) == [saved.json()]
        assert client.get(review_url).json()["items"] == [review]
    restarted.close()


def test_the_list_is_paged_sorted_searched_and_filtered(tmp_path: Path) -> None:
    wb = _workbench(tmp_path, sqlite=True)
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        project = client.post(API + "/projects", json={"name": "Tender"}).json()
        url = API + f"/projects/{project['project_id']}"
        bill = upload(client, _csv(ROWS), "Rohbau.csv").json()["document"]["document_id"]
        client.put(url + "/documents", json={"document_id": bill})
        assert client.post(url + "/validation").status_code == 202
        wb.jobs.shutdown()
        listing = url + "/clarifications"
        every = client.get(listing, params={"limit": 100}).json()
        questions = every["total"]
        assert questions >= 3, "the synthetic bill asks the client several questions"
        email = {
            "document_id": bill,
            "risk_id": "risk_steel",
            "tier": "low",
            "title": "Steel price for the anchors",
            "recipient": "planner@example.com",
            "subject": "Steel price",
            "body": "Which price applies?",
        }
        mailed = client.post(listing + "/emails", json=email).json()
        due = client.put(
            API + f"/clarifications/{mailed['clarification_id']}",
            json={"title": email["title"], "status": "sent", "due": "2026-12-03"},
        ).json()

        # Ten a page by default, the most urgent priority first, and the total of every page.
        first = client.get(listing).json()
        assert (first["total"], first["offset"], first["limit"]) == (questions + 1, 0, 10)
        assert len(first["items"]) == min(10, questions + 1)
        rank = ["critical", "high", "medium", "low", "info"]
        tiers = [rank.index(item["tier"]) for item in every["items"]]
        assert tiers == sorted(tiers)
        second = client.get(listing, params={"offset": 1, "limit": 1}).json()
        assert second["items"] == every["items"][1:2] and second["total"] == questions + 1
        assert client.get(listing, params={"offset": 500}).json()["items"] == []

        def ids(**params: str) -> list[str | None]:
            page = client.get(listing, params={"limit": 100, **params}).json()
            return [item["clarification_id"] for item in page["items"]]

        mine = [due["clarification_id"]]
        # The search reads the item, its bill, its recipient and its answer.
        assert ids(search="PLANNER") == mine
        assert ids(search="steel anchors") == mine
        assert len(ids(search="rohbau")) == questions + 1
        assert ids(kind="subcontractor") == []
        assert ids(status="sent") == mine
        assert ids(status="suggested") == [None] * questions
        assert ids(phase="after_award") == []
        assert ids(due_by="2026-12-05") == mine
        assert ids(due_by="2026-12-01") == []
        for bad in ({"limit": 0}, {"limit": 101}, {"status": "lost"}, {"due_by": "soon"}):
            assert client.get(listing, params=bad).status_code == 422, bad
    wb.close()


def test_the_questions_are_read_once_until_a_finding_is_reviewed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wb = _workbench(tmp_path, sqlite=True)
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        project = client.post(API + "/projects", json={"name": "Tender"}).json()
        url = API + f"/projects/{project['project_id']}"
        bill = upload(client, _csv(ROWS), "Rohbau.csv").json()["document"]["document_id"]
        client.put(url + "/documents", json={"document_id": bill})
        assert client.post(url + "/validation").status_code == 202
        wb.jobs.shutdown()  # the validation reads the questions once it has finished
        reads: list[str] = []
        read_report = risk_service._base

        def counted(workbench: Any, run_id: str) -> Any:
            reads.append(run_id)
            return read_report(workbench, run_id)

        monkeypatch.setattr(risk_service, "_base", counted)
        listing = url + "/clarifications"
        listed = client.get(listing).json()
        assert listed["total"] and client.get(listing).json() == listed
        assert reads == []  # read when the validation finished, not on each request

        run_id = client.get(url).json()["project"]["validation"]["runs"][bill]
        [issue, *_] = client.get(API + f"/validation-runs/{run_id}/issues").json()["items"]
        review = {"status": "false_positive", "expected_version": issue["version"]}
        reviewed = client.post(API + f"/issues/{issue['issue_id']}/review", json=review)
        assert reviewed.status_code == 200, reviewed.text
        client.get(listing)
        client.get(listing)
        assert reads == [run_id]  # read again once, after the review


def test_after_a_restart_the_questions_are_read_at_start_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wb = _workbench(tmp_path, sqlite=True)
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        project = client.post(API + "/projects", json={"name": "Tender"}).json()
        url = API + f"/projects/{project['project_id']}"
        bill = upload(client, _csv(ROWS), "Rohbau.csv").json()["document"]["document_id"]
        client.put(url + "/documents", json={"document_id": bill})
        assert client.post(url + "/validation").status_code == 202
        wb.jobs.shutdown()
        run_id = client.get(url).json()["project"]["validation"]["runs"][bill]
    wb.close()

    # The same database, started again: nothing is kept in memory yet.
    restarted = _workbench(tmp_path, sqlite=True)
    reads: list[str] = []
    read_report = risk_service._base

    def counted(workbench: Any, run_id: str) -> Any:
        reads.append(run_id)
        return read_report(workbench, run_id)

    monkeypatch.setattr(risk_service, "_base", counted)
    projects.read_questions_at_start(restarted)
    restarted.jobs.shutdown(wait=True)
    assert reads == [run_id]
    with TestClient(create_app(workbench=restarted), base_url="http://localhost") as client:
        assert client.get(url + "/clarifications").json()["total"]
    assert reads == [run_id]  # the first view lists what the start-up read
    restarted.close()
