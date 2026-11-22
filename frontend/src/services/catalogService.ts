/**
 * System and catalogue endpoints: health, domain profiles and the detector registry.
 */
import { apiClient } from './apiClient.ts';
import type { DetectorList, Health } from './apiTypes.ts';

export function getHealth({ signal }: { signal?: AbortSignal } = {}): Promise<Health> {
  return apiClient.get('/health', { signal });
}

/**
 * The detector catalogue. With `profileId`, every descriptor also carries `profile_config`: the
 * configuration a run on that profile uses when the plan sets nothing (`default_config` with the
 * profile's `detector_defaults` merged over it). Without it, `profile_config` and the top-level
 * `profile_id` are `null`.
 */
export function listDetectors({
  profileId,
  signal,
}: {
  profileId?: string | null;
  signal?: AbortSignal;
} = {}): Promise<DetectorList> {
  return apiClient.get('/detectors', { query: { profile_id: profileId }, signal });
}
