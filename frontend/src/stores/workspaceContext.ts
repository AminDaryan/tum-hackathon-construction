import { createContext } from 'react';
import type { DocumentDetail } from '../services/apiTypes.ts';

export interface WorkspaceContextValue {
  activeDocumentId: string | null;
  /** the loaded document detail, or null while loading / when none is active */
  activeDocument: DocumentDetail | null;
  loading: boolean;
  error: Error | null;
  /** refreshes the active document (e.g. after a validation run) */
  reload: () => void;
  setActiveDocumentId: (documentId: string | null) => void;
  clearActiveDocument: () => void;
}

export const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);
