"""Persistent project membership; document originals remain content-addressed and shared."""

from sqlalchemy import select

from app.models.project import Project
from app.repositories.records import load_model, to_payload
from app.repositories.sql.schema import projects
from app.repositories.sql.statements import SqlRepository, insert_rows, update_row


class SqlProjectRepository(SqlRepository):
    def add(self, project: Project) -> None:
        insert_rows(
            self._connection,
            projects,
            [{"project_id": project.project_id, "payload": to_payload(project)}],
            what=f"project {project.project_id!r}",
        )

    def update(self, project: Project) -> None:
        update_row(
            self._connection,
            projects,
            projects.c.project_id == project.project_id,
            {"payload": to_payload(project)},
            what=f"project {project.project_id!r}",
        )

    def get(self, project_id: str) -> Project | None:
        payload = self._connection.execute(
            select(projects.c.payload).where(projects.c.project_id == project_id)
        ).scalar_one_or_none()
        return None if payload is None else load_model(Project, payload, what="project")

    def list(self) -> list[Project]:
        return [
            load_model(Project, payload, what="project")
            for payload in self._connection.execute(
                select(projects.c.payload).order_by(projects.c.project_id)
            ).scalars()
        ]
