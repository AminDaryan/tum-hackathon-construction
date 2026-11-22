import { Navigate, Route, Routes } from 'react-router-dom';
import { CreateProjectPage } from '../features/projects/CreateProjectPage.tsx';
import { EditProjectPage } from '../features/projects/EditProjectPage.tsx';
import { ProjectPage } from '../features/projects/ProjectPage.tsx';
import { FollowUpsPage } from '../features/projects/FollowUpsPage.tsx';
import { ProjectReportPage } from '../features/projects/ProjectReportPage.tsx';
import { ProjectsPage } from '../features/projects/ProjectsPage.tsx';
import { ProjectWorkspacePage } from '../features/projects/ProjectWorkspacePage.tsx';
import { ReportsPage } from '../features/projects/ReportsPage.tsx';
import { SettingsLink } from '../features/settings/SettingsDialog.tsx';
import { UserPage } from '../features/users/UserPage.tsx';
import { UsersPage } from '../features/users/UsersPage.tsx';
import { AppShell } from './AppShell.tsx';
import { LegacyRedirect, OpenDocumentRoute, WorkspaceRedirect } from './legacyRoutes.tsx';
import { NotFoundPage } from './NotFoundPage.tsx';

/**
 * Route table. A project has four pages (Overview, Workspace, Follow-ups, Reports) and its edit
 * page; files open in the project's Workspace. /workspace and the old addresses of the
 * documents, runs, issues and exports pages open the file in its project's Workspace at the
 * matching tab, and the old 3D model and History pages go to Projects.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/projects" replace />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/new" element={<CreateProjectPage />} />
        <Route path="projects/:projectId" element={<ProjectPage />} />
        <Route path="projects/:projectId/workspace" element={<ProjectWorkspacePage />} />
        <Route path="projects/:projectId/follow-ups" element={<FollowUpsPage />} />
        <Route path="projects/:projectId/reports" element={<ReportsPage />} />
        <Route path="projects/:projectId/edit" element={<EditProjectPage />} />
        <Route path="projects/:projectId/report" element={<ProjectReportPage />} />
        <Route path="workspace" element={<WorkspaceRedirect />} />
        <Route path="documents" element={<Navigate to="/workspace" replace />} />
        <Route path="documents/:documentId" element={<OpenDocumentRoute />} />
        <Route path="runs" element={<LegacyRedirect tab="requirements" />} />
        <Route path="runs/:runId" element={<LegacyRedirect tab="requirements" />} />
        <Route path="issues" element={<LegacyRedirect tab="issues" />} />
        <Route path="issues/:issueId" element={<LegacyRedirect tab="issues" />} />
        <Route path="exports" element={<LegacyRedirect tab="export" />} />
        <Route path="history" element={<Navigate to="/projects" replace />} />
        <Route path="coordination" element={<Navigate to="/workspace" replace />} />
        <Route path="users" element={<UsersPage />} />
        <Route path="users/:userId" element={<UserPage />} />
        <Route path="settings" element={<SettingsLink />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
