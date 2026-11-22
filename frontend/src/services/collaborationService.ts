import { apiClient, apiPath, sendRequest } from './apiClient.ts';
import type {
  CommentThread,
  FindingComment,
  FindingTask,
  NotificationList,
  Reviewer,
  ReviewerSession,
  TaskInput,
} from './apiTypes.ts';

export const getReviewerSession = (signal?: AbortSignal) => apiClient.get<ReviewerSession>('/collaboration/session', { signal });
export const chooseReviewer = (name: string) => apiClient.post<Reviewer>('/collaboration/session', { json: { name } });
export const getNotifications = (signal?: AbortSignal) => apiClient.get<NotificationList>('/collaboration/notifications', { signal });
export const readNotification = (id: string) => apiClient.post<{ read: boolean }>(apiPath`/collaboration/notifications/${id}/read`);
export const getComments = (id: string, signal?: AbortSignal) => apiClient.get<CommentThread>(apiPath`/collaboration/issues/${id}/comments`, { signal });
export const postComment = (id: string, body: string) =>
  apiClient.post<FindingComment & { bot_replying: boolean }>(apiPath`/collaboration/issues/${id}/comments`, { json: { body } });
export const putTask = (id: string, task: TaskInput) =>
  apiClient.put<{ task: FindingTask | null }>(apiPath`/collaboration/issues/${id}/task`, { json: task });
export const getRunTasks = (runId: string, signal?: AbortSignal) =>
  apiClient.get<{ items: FindingTask[] }>(apiPath`/collaboration/validation-runs/${runId}/tasks`, { signal });

/**
 * Follows Desvio's answer on a finding as it is written (server-sent events): `onText` gets each
 * new piece of text. Resolves when the answer is stored in the thread, or at once when none is
 * under way. Uses the API client, so the request carries the same sign-in as every other call.
 */
export async function streamAnswer(id: string, onText: (text: string) => void, signal?: AbortSignal): Promise<void> {
  const response = await sendRequest(apiPath`/collaboration/issues/${id}/assistant-stream`, {
    accept: 'text/event-stream',
    signal,
  });
  // A 2xx event stream always has a body.
  const reader = response.body!.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += value;
    let end: number;
    while ((end = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const event = /^event: (.*)$/m.exec(block)?.[1];
      if (event === 'done') {
        reader.cancel();
        return;
      }
      if (event === 'text') {
        const data = block
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trim())
          .join('\n');
        onText(JSON.parse(data).text);
      }
    }
  }
}
