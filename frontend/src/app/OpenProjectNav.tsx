import { useProject } from '../features/projects/ProjectContext.tsx';
import { ProjectNav } from './ProjectNav.tsx';

/** The project bar of the open project; none for a project the server does not have. */
export function OpenProjectNav() {
  const { projectId, notFound } = useProject();
  if (notFound) return null;
  return <ProjectNav projectId={projectId} />;
}
