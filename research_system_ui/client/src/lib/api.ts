import type { LogEvent, Session, SessionStatus } from './types';

const DEFAULT_API_BASE_URL = 'http://localhost:8000';

const rawBaseUrl = import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL;
const API_BASE_URL = rawBaseUrl.replace(/\/$/, '');

function buildApiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE_URL}${normalizedPath}`;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildApiUrl(path), {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`API request failed (${response.status}): ${errorText}`);
  }

  return response.json() as Promise<T>;
}

async function requestText(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(buildApiUrl(path), init);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`API request failed (${response.status}): ${errorText}`);
  }
  return response;
}

function attachJsonEventListener<T>(
  eventSource: EventSource,
  eventName: string,
  onValue: (value: T) => void,
  onError: (error: Error) => void,
): () => void {
  const listener = ((event: MessageEvent<string>) => {
    try {
      onValue(JSON.parse(event.data) as T);
    } catch (error) {
      onError(error instanceof Error ? error : new Error(String(error)));
    }
  }) as EventListener;
  eventSource.addEventListener(eventName, listener);
  return () => eventSource.removeEventListener(eventName, listener);
}

export interface StartResearchRequest {
  topic: string;
  goal?: string;
  domain?: string;
  data_path?: string;
  data_description?: string;
  output_path?: string;
  max_experiments?: number;
  max_fix_iterations?: number;
  force_rework_iterations?: number;
  time_limit?: number;
  frameworks?: string[];
  constraints?: string[];
}

export interface StartResearchResponse {
  run_id: string;
  session_id: string;
  status: string;
}

export interface DeleteSessionResponse {
  deleted: boolean;
}

export type RunStatusResponse = Session;

export interface StreamEndEvent {
  run_id: string;
  session_id: string;
  status: SessionStatus;
  event_count: number;
  artifact_count: number;
}

export interface StreamHandlers {
  onEvent?: (event: LogEvent) => void;
  onEnd?: (event: StreamEndEvent) => void;
  onError?: (error: Event | Error) => void;
}

export interface ArtifactContentResponse {
  run_id: string;
  artifact_path: string;
  resolved_path: string;
  exists: boolean;
  truncated: boolean;
  content: string;
}

export interface ArtifactStreamEvent {
  event_type: 'ARTIFACT_READY' | 'ARTIFACT_END';
  run_id: string;
  artifact_path: string;
  resolved_path?: string;
  reason?: string;
}

export interface ArtifactStreamHandlers {
  onEvent?: (event: ArtifactStreamEvent) => void;
  onError?: (error: Event | Error) => void;
}

export async function getSessions(): Promise<Session[]> {
  return requestJson<Session[]>('/api/v1/sessions');
}

export async function getLogs(runId: string): Promise<LogEvent[]> {
  return requestJson<LogEvent[]>(`/api/v1/sessions/${encodeURIComponent(runId)}/logs`);
}

export async function getArtifactContent(
  runId: string,
  artifactPath: string,
  maxBytes = 65536,
): Promise<ArtifactContentResponse> {
  const query = new URLSearchParams({
    path: artifactPath,
  });
  const response = await requestText(`/api/v1/research/${encodeURIComponent(runId)}/artifacts/content?${query.toString()}`);
  const content = await response.text();
  const truncated = content.length > maxBytes;
  return {
    run_id: runId,
    artifact_path: artifactPath,
    resolved_path: artifactPath,
    exists: true,
    truncated,
    content: truncated ? content.slice(0, maxBytes) : content,
  };
}

export async function deleteSession(runId: string): Promise<DeleteSessionResponse> {
  return requestJson<DeleteSessionResponse>(`/api/v1/sessions/${encodeURIComponent(runId)}`, {
    method: 'DELETE',
  });
}

export async function startResearch(payload: StartResearchRequest): Promise<StartResearchResponse> {
  return requestJson<StartResearchResponse>('/api/v1/research', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getStatus(runId: string): Promise<RunStatusResponse> {
  return requestJson<RunStatusResponse>(`/api/v1/research/${encodeURIComponent(runId)}/status`);
}

export function streamLogs(runId: string, handlers: StreamHandlers = {}): () => void {
  const eventSource = new EventSource(buildApiUrl(`/api/v1/research/${encodeURIComponent(runId)}/stream`));
  const detachLog = attachJsonEventListener<LogEvent>(
    eventSource,
    'log',
    (event) => handlers.onEvent?.(event),
    (error) => handlers.onError?.(error),
  );
  const detachEnd = attachJsonEventListener<StreamEndEvent>(
    eventSource,
    'end',
    (event) => {
      handlers.onEnd?.(event);
      eventSource.close();
    },
    (error) => handlers.onError?.(error),
  );

  eventSource.onerror = (event) => {
    handlers.onError?.(event);
  };

  return () => {
    detachLog();
    detachEnd();
    eventSource.close();
  };
}

export function streamArtifactContent(
  runId: string,
  artifactPath: string,
  handlers: ArtifactStreamHandlers = {},
): () => void {
  const query = new URLSearchParams({ path: artifactPath });
  const eventSource = new EventSource(
    buildApiUrl(`/api/v1/research/${encodeURIComponent(runId)}/artifacts/stream?${query.toString()}`),
  );

  const detachArtifact = attachJsonEventListener<Record<string, unknown>>(
    eventSource,
    'artifact',
    (event) => {
      const resolvedPath = typeof event.path === 'string' ? event.path : artifactPath;
      handlers.onEvent?.({
        event_type: 'ARTIFACT_READY',
        run_id: runId,
        artifact_path: resolvedPath,
        resolved_path: resolvedPath,
        reason: typeof event.label === 'string' ? event.label : 'artifact_update',
      });
    },
    (error) => handlers.onError?.(error),
  );
  const detachEnd = attachJsonEventListener<Record<string, unknown>>(
    eventSource,
    'end',
    () => {
      handlers.onEvent?.({
        event_type: 'ARTIFACT_END',
        run_id: runId,
        artifact_path: artifactPath,
        resolved_path: artifactPath,
        reason: 'stream_complete',
      });
      eventSource.close();
    },
    (error) => handlers.onError?.(error),
  );

  eventSource.onerror = (event) => {
    handlers.onError?.(event);
  };

  return () => {
    detachArtifact();
    detachEnd();
    eventSource.close();
  };
}

// ── V4 Interaction endpoints ───────────────────────────────────────────────────

export interface ApproveRequest {
  action: 'approve' | 'reject' | 'modify';
  feedback?: string;
}

export interface ApproveResponse {
  run_id: string;
  action: string;
  message: string;
}

export interface GuidanceRequest {
  file_path: string;
  user_action: 'continue' | 'skip' | 'provide_fix' | 'manual_edit';
  hint?: string;
}

export interface GuidanceResponse {
  run_id: string;
  file_path: string;
  user_action: string;
  message: string;
}

export interface ApprovalStatusResponse {
  run_id: string;
  awaiting_approval: boolean;
  plan?: Record<string, unknown>;
}

export interface GuidanceStatusResponse {
  run_id: string;
  awaiting_guidance: boolean;
  file_path?: string;
  error?: string;
  attempts?: number;
  options?: string[];
}

export async function approvePlan(runId: string, payload: ApproveRequest): Promise<ApproveResponse> {
  return requestJson<ApproveResponse>(`/api/v1/runs/${encodeURIComponent(runId)}/approve`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function provideGuidance(runId: string, payload: GuidanceRequest): Promise<GuidanceResponse> {
  return requestJson<GuidanceResponse>(`/api/v1/runs/${encodeURIComponent(runId)}/guidance`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function cancelRun(runId: string): Promise<{ run_id: string; message: string }> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(runId)}`, { method: 'DELETE' });
}

export async function getApprovalStatus(runId: string): Promise<ApprovalStatusResponse> {
  return requestJson<ApprovalStatusResponse>(`/api/v1/runs/${encodeURIComponent(runId)}/approval_status`);
}

export async function getGuidanceStatus(runId: string): Promise<GuidanceStatusResponse> {
  return requestJson<GuidanceStatusResponse>(`/api/v1/runs/${encodeURIComponent(runId)}/guidance_status`);
}

// ── Sprint 1-4 신규 엔드포인트 ────────────────────────────────────────────────

export interface InjectContextRequest {
  context: string;
  phase?: number;
}

export async function injectContext(
  runId: string,
  context: string,
  phase = -1,
): Promise<void> {
  await requestJson<{ status: string }>(
    `/api/v1/runs/${encodeURIComponent(runId)}/inject`,
    {
      method: 'POST',
      body: JSON.stringify({ context, phase } satisfies InjectContextRequest),
    },
  );
}

export async function acceptExtensionProposal(
  _runId: string,
  proposal: string,
  originalTopic: string,
): Promise<{ run_id: string }> {
  return requestJson<{ run_id: string }>('/api/v1/research', {
    method: 'POST',
    body: JSON.stringify({
      topic: originalTopic,
      goal: `[Extension] ${proposal}`,
    }),
  });
}

export { API_BASE_URL };
