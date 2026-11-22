import { useMemo } from 'react';
import type { DetectorDescriptor, DetectorList } from '../services/apiTypes.ts';
import { listDetectors } from '../services/catalogService.ts';
import { type ApiResource, useApiResource } from './useApiResource.ts';

/**
 * Loads the detector registry catalogue (GET /detectors) and indexes it by detector id, so
 * pages can show detector names and categories next to ids. With `profileId`, the descriptors
 * carry that profile's resolved defaults (`profile_config`); the run configuration asks for
 * them, every other page loads the plain catalogue.
 */
export function useDetectorCatalogue({
  profileId = null,
}: {
  profileId?: string | null;
} = {}): ApiResource<DetectorList> & {
  detectors: DetectorDescriptor[];
  byId: Map<string, DetectorDescriptor>;
} {
  const resource = useApiResource((signal) => listDetectors({ profileId, signal }), [profileId]);
  const detectors = useMemo(() => resource.data?.items ?? [], [resource.data]);
  const byId = useMemo(
    () => new Map(detectors.map((descriptor) => [descriptor.spec.detector_id, descriptor])),
    [detectors],
  );
  return { ...resource, detectors, byId };
}
