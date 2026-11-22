import { Outlet } from 'react-router-dom';
import { useProject } from '../features/projects/ProjectContext.tsx';
import { NotFoundPage } from './NotFoundPage.tsx';

/** The page of a project, or the not-found page on every page of a project the server does not have. */
export function ProjectOutlet() {
  const { notFound } = useProject();
  return notFound ? <NotFoundPage projectMissing /> : <Outlet />;
}
