"""Two real browser sessions discuss a persisted finding, with recipient-only mentions."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.integration.test_api import _workbench
from tests.unit.repositories.postgres import POSTGRESQL, backends

API = "/api/v1"
COLLAB = API + "/collaboration"


def test_two_reviewers_comments_mentions_and_restart(tmp_path: Path) -> None:
    wb = _workbench(tmp_path, sqlite=True)
    app = create_app(workbench=wb)
    with (
        TestClient(app, base_url="http://localhost") as larissa,
        TestClient(app, base_url="http://localhost") as johan,
    ):
        assert larissa.get(COLLAB + "/session").json()["reviewer"] is None
        assert larissa.get(COLLAB + "/notifications").status_code == 422
        assert larissa.post(COLLAB + "/session", json={"name": "Larissa"}).status_code == 200
        assert johan.post(COLLAB + "/session", json={"name": "Johan"}).status_code == 200
        assert larissa.get(COLLAB + "/session").json()["reviewer"]["handle"] == "larissa"
        assert johan.get(COLLAB + "/session").json()["reviewer"]["handle"] == "johan"
        assert (
            "HttpOnly"
            in johan.post(COLLAB + "/session", json={"name": "Johan"}).headers["set-cookie"]
        )
        uploaded = larissa.post(
            API + "/documents",
            files={
                "file": (
                    "demo.csv",
                    "Item;Description;Quantity;Unit;Unit price;Total\n1;Pipe;10;m;7;750\n",
                )
            },
        ).json()
        dataset_id = uploaded["dataset"]["dataset_id"]
        run = larissa.post(API + f"/datasets/{dataset_id}/validation-runs", json={}).json()
        run_id = run["run_id"]
        findings = larissa.get(API + f"/validation-runs/{run_id}/issues").json()["items"]
        issue = next(f for f in findings if f["row_id"])
        thread = COLLAB + f"/issues/{issue['issue_id']}/comments"
        assert larissa.post(thread, json={"body": "   "}).status_code == 422
        assert larissa.post(thread, json={"body": "@missing take a look"}).status_code == 422
        assert larissa.post(thread, json={"body": "Hi", "author": "johan"}).status_code == 422
        assert (
            larissa.post(COLLAB + "/issues/missing/comments", json={"body": "Hi"}).status_code
            == 404
        )
        assert larissa.get(thread).json()["items"] == []
        body = "@Johan check this out. @johan, the line total looks wrong. @larissa"
        posted = larissa.post(thread, json={"body": body})
        assert posted.status_code == 201, posted.text
        comment_id = posted.json()["comment_id"]
        inbox = johan.get(COLLAB + "/notifications").json()
        assert inbox["unread_count"] == 1 and len(inbox["items"]) == 1
        notification = inbox["items"][0]
        assert notification["document_id"] == uploaded["document"]["document_id"]
        assert notification["validation_run_id"] == run_id
        assert notification["issue_id"] == issue["issue_id"]
        assert notification["comment_id"] == comment_id
        assert notification["author_name"] == "Larissa" and notification["body"] == body
        assert larissa.get(COLLAB + "/notifications").json()["unread_count"] == 0
        read_url = COLLAB + f"/notifications/{notification['notification_id']}/read"
        assert larissa.post(read_url).status_code == 404
        assert johan.post(read_url).status_code == 200
        assert johan.post(read_url).status_code == 200  # idempotent
        assert johan.get(COLLAB + "/notifications").json()["unread_count"] == 0
        assert (
            johan.post(thread, json={"body": "@larissa I will check the calculation."}).status_code
            == 201
        )
        assert larissa.get(COLLAB + "/notifications").json()["unread_count"] == 1
        assert [c["author_name"] for c in johan.get(thread).json()["items"]] == ["Larissa", "Johan"]
        # Tasks: separate from the review decision, logged in the thread, assignment notifies.
        task_url = COLLAB + f"/issues/{issue['issue_id']}/task"
        assert larissa.get(thread).json()["task"] is None
        assert larissa.put(task_url, json={"assignee": "nobody"}).status_code == 422
        assert larissa.put(task_url, json={"status": "finished"}).status_code == 422
        assigned = larissa.put(task_url, json={"assignee": "Johan", "task_type": "fix"})
        assert assigned.status_code == 200, assigned.text
        task = assigned.json()["task"]
        assert (task["assignee"], task["assignee_name"], task["status"], task["task_type"]) == (
            "johan",
            "Johan",
            "todo",
            "fix",
        )
        assert task["updated_by"] == "larissa"
        inbox = johan.get(COLLAB + "/notifications").json()
        assert inbox["unread_count"] == 1
        assert inbox["items"][0]["kind"] == "activity"
        assert inbox["items"][0]["body"] == "assigned Johan, set type to Fix"
        assert inbox["items"][0]["issue_id"] == issue["issue_id"]
        # Saving the same task again changes nothing and logs nothing.
        before = len(johan.get(thread).json()["items"])
        larissa.put(task_url, json={"assignee": "johan", "task_type": "fix"})
        assert len(johan.get(thread).json()["items"]) == before
        # The assignee updating their own task does not notify anyone.
        johan.put(task_url, json={"assignee": "johan", "status": "done", "task_type": "fix"})
        assert johan.get(COLLAB + "/notifications").json()["unread_count"] == 1
        assert larissa.get(COLLAB + "/notifications").json()["unread_count"] == 1
        entries = johan.get(thread).json()["items"]
        assert [(e["kind"], e["author_name"], e["body"]) for e in entries[-2:]] == [
            ("activity", "Larissa", "assigned Johan, set type to Fix"),
            ("activity", "Johan", "set status to Done"),
        ]
        # Opening one notification reads the recipient's other notifications on that finding.
        assert larissa.post(thread, json={"body": "@johan see the task"}).status_code == 201
        unread = johan.get(COLLAB + "/notifications").json()
        assert unread["unread_count"] == 2
        johan.post(COLLAB + f"/notifications/{unread['items'][0]['notification_id']}/read")
        assert johan.get(COLLAB + "/notifications").json()["unread_count"] == 0
        run_tasks = larissa.get(COLLAB + f"/validation-runs/{run_id}/tasks").json()["items"]
        assert [(t["issue_id"], t["status"]) for t in run_tasks] == [(issue["issue_id"], "done")]
        assert larissa.get(COLLAB + "/validation-runs/missing/tasks").json()["items"] == []
        # The review decision is untouched by the task.
        assert (
            larissa.get(API + f"/issues/{issue['issue_id']}").json()["issue"]["review_status"]
            == issue["review_status"]
        )
        cookies = dict(johan.cookies)
    wb.close()
    # Reopen the on-disk database, not just another connection or app with the same objects.
    restarted = _workbench(tmp_path, sqlite=True)
    with TestClient(create_app(workbench=restarted), base_url="http://localhost") as client:
        client.cookies.update(cookies)
        assert client.get(COLLAB + "/session").json()["reviewer"]["handle"] == "johan"
        assert len(client.get(thread).json()["items"]) == 5
        assert client.get(thread).json()["task"]["status"] == "done"
        inbox = client.get(COLLAB + "/notifications").json()
        assert inbox["unread_count"] == 0
        assert [(n["kind"], n["is_read"]) for n in inbox["items"]] == [
            ("comment", 1),
            ("activity", 1),
            ("comment", 1),
        ]
    restarted.close()


@pytest.mark.parametrize("backend", backends("sqlite"))
def test_task_due_dates_are_optional_validated_logged_and_persisted(
    tmp_path: Path,
    backend: str,
) -> None:
    wb = _workbench(tmp_path, sqlite=backend == "sqlite", postgresql=backend == POSTGRESQL)
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        client.post(COLLAB + "/session", json={"name": "Amin"})
        uploaded = client.post(
            API + "/documents",
            files={
                "file": (
                    "deadline.csv",
                    "Item;Description;Quantity;Unit;Unit price;Total\n1;Pipe;10;m;7;750\n",
                )
            },
        ).json()
        run = client.post(
            API + f"/datasets/{uploaded['dataset']['dataset_id']}/validation-runs", json={}
        ).json()
        issue = client.get(API + f"/validation-runs/{run['run_id']}/issues").json()["items"][0]
        task_url = COLLAB + f"/issues/{issue['issue_id']}/task"
        thread = COLLAB + f"/issues/{issue['issue_id']}/comments"
        assert client.put(task_url, json={"assignee": "amin"}).json()["task"]["due_date"] is None
        for invalid in ("2026-02-30", "tomorrow"):
            assert client.put(task_url, json={"due_date": invalid}).status_code == 422
        # A year typed short or half-typed (the date picker sent 0002-01-02) is not a deadline.
        for impossible in ("0002-01-02", "0026-12-18", "1999-12-31", "2101-01-01"):
            rejected = client.put(task_url, json={"due_date": impossible})
            assert rejected.status_code == 422
            assert "between 2000-01-01 and 2100-12-31" in rejected.json()["error"]["message"]
        assert client.get(thread).json()["task"]["due_date"] is None
        task = {
            "assignee": "amin",
            "status": "waiting",
            "task_type": "ask_client",
            "due_date": "2026-12-03",
        }
        assert client.put(task_url, json=task).json()["task"]["due_date"] == "2026-12-03"
        assert client.get(thread).json()["items"][-1]["body"].endswith("set due date to 2026-12-03")
        before = len(client.get(thread).json()["items"])
        client.put(task_url, json=task)
        assert len(client.get(thread).json()["items"]) == before
        listed = client.get(COLLAB + f"/validation-runs/{run['run_id']}/tasks").json()["items"][0]
        assert listed["due_date"] == "2026-12-03"
        task["due_date"] = None
        cleared = client.put(task_url, json=task).json()["task"]
        assert cleared["due_date"] is None and cleared["status"] == "waiting"
        assert client.get(thread).json()["items"][-1]["body"] == "cleared the due date"
        task["due_date"] = "2028-02-29"
        client.put(task_url, json=task)
    wb.close()
    if backend == "sqlite":
        restarted = _workbench(tmp_path, sqlite=True)
        with TestClient(create_app(workbench=restarted), base_url="http://localhost") as client:
            assert client.get(thread).json()["task"]["due_date"] == "2028-02-29"
        restarted.close()


def test_team_reviewers_are_seeded_at_start_and_others_can_join(tmp_path: Path) -> None:
    wb = _workbench(tmp_path, sqlite=True)
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        names = [r["name"] for r in client.get(COLLAB + "/session").json()["reviewers"]]
        assert names == ["Amin", "Imants", "Johan", "Larissa", "Muhammad", "Ziyu"]
        assert client.post(COLLAB + "/session", json={"name": "Johan"}).status_code == 200
        assert client.post(COLLAB + "/session", json={"name": "Ziyu"}).status_code == 200
        assert client.get(COLLAB + "/session").json()["reviewer"]["handle"] == "ziyu"
    wb.close()
    # A restart adds nothing twice and keeps the reviewers who joined.
    restarted = _workbench(tmp_path, sqlite=True)
    with TestClient(create_app(workbench=restarted), base_url="http://localhost") as client:
        handles = [r["handle"] for r in client.get(COLLAB + "/session").json()["reviewers"]]
        assert handles == ["amin", "imants", "johan", "larissa", "muhammad", "ziyu"]
    restarted.close()


def test_a_task_comments_and_clarification_follow_the_finding_to_the_next_run(
    tmp_path: Path,
) -> None:
    wb = _workbench(tmp_path, sqlite=True)
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        client.post(COLLAB + "/session", json={"name": "Amin"})
        csv = "Item;Description;Quantity;Unit;Unit price;Total\n1;Pipe;10;m;7;750\n"
        csv += "2;Valve;2;St;5;10\n"
        dataset = client.post(API + "/documents", files={"file": ("b.csv", csv)}).json()["dataset"]
        ds, [table] = dataset["dataset_id"], dataset["tables"]
        runs_url = API + f"/datasets/{ds}/validation-runs"
        first = client.post(runs_url, json={}).json()
        issue = client.get(API + f"/validation-runs/{first['run_id']}/issues").json()["items"][0]
        task = {"assignee": "amin", "status": "in_progress", "task_type": "fix"}
        task["due_date"] = "2026-12-03"
        client.put(COLLAB + f"/issues/{issue['issue_id']}/task", json=task)
        client.post(COLLAB + f"/issues/{issue['issue_id']}/comments", json={"body": "Ask Ann."})
        project = client.post(API + "/projects", json={"name": "Tender"}).json()
        project_url = API + f"/projects/{project['project_id']}"
        client.put(project_url + "/documents", json={"document_id": dataset["document_id"]})
        email = {
            "document_id": dataset["document_id"],
            "risk_id": "risk_total",
            "tier": "high",
            "title": "Line total",
            "issue_id": issue["issue_id"],
            "subject": "Line total",
            "body": "Which total is right?",
        }
        assert client.post(project_url + "/clarifications/emails", json=email).status_code == 200

        # Nothing changed: the same run, no new one.
        assert client.post(runs_url, json={}).json()["run_id"] == first["run_id"]
        # An unrelated edit: a new run, and the finding's task, thread and email follow it.
        description = next(
            c["column_id"] for c in table["columns"] if c["mapped_semantic_field"] == "description"
        )
        rows = client.get(API + f"/datasets/{ds}/tables/{table['table_id']}/rows").json()["items"]
        fix = {"table_id": table["table_id"], "row_id": rows[-1]["row_id"]}
        fix |= {"column_id": description, "raw_value": "Gate valve"}
        client.post(
            API + f"/datasets/{ds}/corrections", json={"expected_revision": 1, "corrections": [fix]}
        )
        second = client.post(runs_url, json={}).json()
        assert second["run_id"] != first["run_id"]
        found = client.get(API + f"/validation-runs/{second['run_id']}/issues").json()["items"]
        [same] = [i for i in found if i["fingerprint"] == issue["fingerprint"]]
        assert same["issue_id"] != issue["issue_id"]
        thread = client.get(COLLAB + f"/issues/{same['issue_id']}/comments").json()
        assert thread["task"]["assignee"] == "amin" and thread["task"]["status"] == "in_progress"
        assert thread["task"]["task_type"] == "fix" and thread["task"]["due_date"] == "2026-12-03"
        assert "Ask Ann." in [item["body"] for item in thread["items"]]
        listed = client.get(COLLAB + f"/validation-runs/{second['run_id']}/tasks").json()["items"]
        assert [t["issue_id"] for t in listed] == [same["issue_id"]]
        [clarification] = [
            item
            for item in client.get(project_url + "/clarifications").json()["items"]
            if item["clarification_id"]
        ]
        assert clarification["issue_id"] == same["issue_id"]
    wb.close()
