import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useApiResource } from '../hooks/useApiResource.ts';
import { getDocument } from '../services/documentsService.ts';
import { readActiveDocumentId, writeActiveDocumentId } from './activeDocumentStorage.ts';
import { WorkspaceContext } from './workspaceContext.ts';

/**
 * Holds the active document: its id (remembered across reloads) and its loaded detail
 * (GET /documents/{id}, including the dataset summary). Pages read it through useWorkspace().
 */
export function WorkspaceProvider({ children }: { children?: ReactNode }) {
  const [params] = useSearchParams();
  const linkedDocument = params.get('document');
  const [activeDocumentId, setActiveDocumentIdState] = useState<string | null>(() => linkedDocument || readActiveDocumentId());
  const setActiveDocumentId = useCallback((documentId: string | null) => {
    const next = documentId || null;
    setActiveDocumentIdState(next);
    writeActiveDocumentId(next);
  }, []);
  const clearActiveDocument = useCallback(() => setActiveDocumentId(null), [setActiveDocumentId]);

  useEffect(() => {
    if (linkedDocument) setActiveDocumentId(linkedDocument);
  }, [linkedDocument, setActiveDocumentId]);

  const resource = useApiResource(
    async (signal) => {
      try {
        // The resource is enabled only while there is an id.
        return await getDocument(activeDocumentId!, { signal });
      } catch (error) {
        // A redeploy or deletion can leave a remembered id behind. Only forget a confirmed
        // missing file, and never let an obsolete request clear a newer selection.
        if (!signal.aborted && (error as { code?: unknown }).code === 'not_found') clearActiveDocument();
        throw error;
      }
    },
    [activeDocumentId],
    { enabled: Boolean(activeDocumentId) },
  );

  const loaded = resource.data;
  const activeDocument =
    loaded && loaded.document?.document_id === activeDocumentId ? loaded : null;

  const value = useMemo(
    () => ({
      activeDocumentId,
      activeDocument,
      loading: resource.loading,
      error: resource.error,
      reload: resource.reload,
      setActiveDocumentId,
      clearActiveDocument,
    }),
    [
      activeDocumentId,
      activeDocument,
      resource.loading,
      resource.error,
      resource.reload,
      setActiveDocumentId,
      clearActiveDocument,
    ],
  );

  return <WorkspaceContext value={value}>{children}</WorkspaceContext>;
}
