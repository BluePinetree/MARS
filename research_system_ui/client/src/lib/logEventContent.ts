import type { LogEvent } from './types';

export type RenderKind = 'markdown' | 'json' | 'code' | 'text';

export interface RenderDescriptor {
  kind: RenderKind;
  text: string;
  language: string;
  parsed?: unknown;
}

export interface StatusSnapshot {
  executionSuccess?: boolean;
  needsRework?: boolean;
  readyForReport?: boolean;
  feedbackForCoder?: string;
  summary?: string;
  iterationLabel?: string;
  validationTier?: string;
  qualityGateStatus?: string;
  reportReadyHint?: boolean;
  executionPolicyViolated?: boolean;
  blockerFixMode?: boolean;
  failureFingerprint?: string;
  failureRepeatCount?: number;
  failureRootCause?: string;
}

type EventShape = Pick<LogEvent, 'content' | 'metadata'>;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function coerceBoolean(value: unknown): boolean | undefined {
  if (typeof value === 'boolean') {
    return value;
  }
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (normalized === 'true') {
      return true;
    }
    if (normalized === 'false') {
      return false;
    }
  }
  return undefined;
}

function coerceNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return undefined;
}

function extractAssignment(content: string, key: string): string | undefined {
  const regex = new RegExp(`${key}\\s*[:=]\\s*([^\\n;]+)`, 'i');
  const match = content.match(regex);
  return match?.[1]?.trim();
}

function normalizeLanguage(languageHint?: string): string {
  const normalized = (languageHint || '').trim().toLowerCase();
  if (!normalized) {
    return 'text';
  }
  if (normalized === 'py') {
    return 'python';
  }
  if (normalized === 'ts') {
    return 'typescript';
  }
  if (normalized === 'js') {
    return 'javascript';
  }
  if (normalized === 'yml') {
    return 'yaml';
  }
  if (normalized === 'md') {
    return 'markdown';
  }
  return normalized;
}

export function extractIterationLabel(content?: string): string | undefined {
  if (!content) {
    return undefined;
  }
  const match = content.match(/iteration\s*[_ ]?(\d+)/i);
  return match ? `Iteration ${match[1]}` : undefined;
}

export function extractJsonValue(content?: string): unknown | null {
  if (!content) {
    return null;
  }

  const trimmed = content.trim();
  const candidates = new Set<string>();

  if (trimmed) {
    candidates.add(trimmed);
  }

  const fencedJson = trimmed.match(/```json\s*([\s\S]*?)```/i);
  if (fencedJson?.[1]) {
    candidates.add(fencedJson[1].trim());
  }

  const fencedAny = trimmed.match(/```[a-zA-Z0-9_-]*\s*([\s\S]*?)```/);
  if (fencedAny?.[1]) {
    candidates.add(fencedAny[1].trim());
  }

  const firstBrace = trimmed.indexOf('{');
  const lastBrace = trimmed.lastIndexOf('}');
  if (firstBrace >= 0 && lastBrace > firstBrace) {
    candidates.add(trimmed.slice(firstBrace, lastBrace + 1).trim());
  }

  const firstBracket = trimmed.indexOf('[');
  const lastBracket = trimmed.lastIndexOf(']');
  if (firstBracket >= 0 && lastBracket > firstBracket) {
    candidates.add(trimmed.slice(firstBracket, lastBracket + 1).trim());
  }

  for (const candidate of Array.from(candidates)) {
    if (!candidate) {
      continue;
    }
    const startsLikeJson =
      (candidate.startsWith('{') && candidate.endsWith('}')) ||
      (candidate.startsWith('[') && candidate.endsWith(']'));
    if (!startsLikeJson) {
      continue;
    }
    try {
      return JSON.parse(candidate);
    } catch {
      continue;
    }
  }

  return null;
}

export function extractJsonObject(content?: string): Record<string, unknown> | null {
  const parsed = extractJsonValue(content);
  return isPlainObject(parsed) ? parsed : null;
}

export function looksLikeMarkdown(text: string): boolean {
  if (!text.trim()) {
    return false;
  }

  const patterns = [
    /^#{1,6}\s/m,
    /^\s*[-*+]\s/m,
    /^\s*\d+\.\s/m,
    /^>\s/m,
    /```/,
    /\[[^\]]+\]\([^)]+\)/,
    /(^|\s)\*\*[^*]+\*\*/,
    /(^|\s)_[^_]+_/,
    /^\|.+\|\s*$/m,
  ];

  return patterns.some((pattern) => pattern.test(text));
}

export function looksLikeCode(text: string): boolean {
  if (!text.trim()) {
    return false;
  }

  const patterns = [
    /^\s*(from|import|def|class|async def)\s+/m,
    /^\s*(const|let|var|function|interface|type)\s+/m,
    /^\s*(SELECT|WITH|INSERT|UPDATE|DELETE)\s+/im,
    /^\s*#!/m,
    /=>/,
    /;\s*$/m,
    /{\s*[\r\n]/,
    /<\/?[A-Za-z][^>]*>/,
  ];

  return patterns.some((pattern) => pattern.test(text));
}

export function inferCodeLanguage(text: string, languageHint?: string): string {
  const hinted = normalizeLanguage(languageHint);
  if (hinted !== 'text') {
    return hinted;
  }

  const trimmed = text.trim();
  if (!trimmed) {
    return 'text';
  }

  if (
    (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
    (trimmed.startsWith('[') && trimmed.endsWith(']'))
  ) {
    return 'json';
  }
  if (/^\s*(from|import|def|class|async def)\s+/m.test(text)) {
    return 'python';
  }
  if (/^\s*(const|let|var|function|interface|type)\s+/m.test(text) || /=>/.test(text)) {
    return /:\s*(string|number|boolean|unknown|Record<)/.test(text) ? 'typescript' : 'javascript';
  }
  if (/^\s*(SELECT|WITH|INSERT|UPDATE|DELETE)\s+/im.test(text)) {
    return 'sql';
  }
  if (/^\s*#!/m.test(text) || /^\s*\$ /m.test(text)) {
    return 'bash';
  }
  if (/^\s*<\?xml|<\/?[A-Za-z][^>]*>/.test(text)) {
    return 'xml';
  }
  if (/^\s*[\w-]+\s*:\s*.+$/m.test(text)) {
    return 'yaml';
  }
  return 'text';
}

function unwrapFencedBlock(text: string): { language?: string; body: string } | null {
  const match = text.trim().match(/^```([a-zA-Z0-9_+-]*)\s*\n?([\s\S]*?)\n?```$/);
  if (!match) {
    return null;
  }
  return {
    language: normalizeLanguage(match[1]),
    body: match[2].trim(),
  };
}

export function inferRenderContent(
  value: unknown,
  options?: {
    languageHint?: string;
    eventType?: string;
    keyHint?: string;
    preferMarkdown?: boolean;
  },
): RenderDescriptor {
  const languageHint = normalizeLanguage(options?.languageHint);
  const eventType = options?.eventType || '';
  const keyHint = (options?.keyHint || '').toLowerCase();

  if (value === null || value === undefined) {
    return { kind: 'text', text: '', language: 'text' };
  }

  if (typeof value !== 'string') {
    return {
      kind: 'json',
      text: JSON.stringify(value, null, 2),
      language: 'json',
      parsed: value,
    };
  }

  const text = value.trim();
  if (!text) {
    return { kind: 'text', text: '', language: 'text' };
  }

  const fenced = unwrapFencedBlock(text);
  if (fenced) {
    if (fenced.language === 'json') {
      const parsed = extractJsonValue(fenced.body);
      return {
        kind: 'json',
        text: JSON.stringify(parsed ?? fenced.body, null, 2),
        language: 'json',
        parsed: parsed ?? fenced.body,
      };
    }
    if (fenced.language === 'markdown') {
      return { kind: 'markdown', text: fenced.body, language: 'markdown' };
    }
    return {
      kind: 'code',
      text: fenced.body,
      language: inferCodeLanguage(fenced.body, fenced.language || languageHint),
    };
  }

  const parsedJson = extractJsonValue(text);
  if (parsedJson !== null && !looksLikeMarkdown(text)) {
    return {
      kind: 'json',
      text: JSON.stringify(parsedJson, null, 2),
      language: 'json',
      parsed: parsedJson,
    };
  }

  if (options?.preferMarkdown || keyHint.includes('report') || languageHint === 'markdown' || looksLikeMarkdown(text)) {
    return { kind: 'markdown', text, language: 'markdown' };
  }

  const forceCode =
    eventType === 'CODE_BLOCK' ||
    keyHint.includes('code') ||
    keyHint.includes('script') ||
    languageHint !== 'text';
  if (forceCode || looksLikeCode(text)) {
    return {
      kind: 'code',
      text,
      language: inferCodeLanguage(text, languageHint),
    };
  }

  return { kind: 'text', text, language: 'text' };
}

export function extractStatusSnapshot(event: EventShape): StatusSnapshot | null {
  const content = event.content || '';
  const metadataRoot = isPlainObject(event.metadata) ? event.metadata : null;
  const metadataSnapshot = isPlainObject(event.metadata?.status_snapshot)
    ? event.metadata.status_snapshot
    : null;
  const jsonSnapshot = extractJsonObject(content);

  const snapshot: StatusSnapshot = {
    executionSuccess:
      coerceBoolean(metadataSnapshot?.execution_success) ??
      coerceBoolean(metadataRoot?.execution_success) ??
      coerceBoolean(jsonSnapshot?.execution_success) ??
      coerceBoolean(extractAssignment(content, 'execution_success')),
    needsRework:
      coerceBoolean(metadataSnapshot?.needs_rework) ??
      coerceBoolean(metadataRoot?.needs_rework) ??
      coerceBoolean(jsonSnapshot?.needs_rework) ??
      coerceBoolean(extractAssignment(content, 'needs_rework')),
    readyForReport:
      coerceBoolean(metadataSnapshot?.ready_for_report) ??
      coerceBoolean(metadataRoot?.ready_for_report) ??
      coerceBoolean(jsonSnapshot?.ready_for_report) ??
      coerceBoolean(extractAssignment(content, 'ready_for_report')),
    feedbackForCoder:
      (typeof metadataSnapshot?.feedback_for_coder === 'string' && metadataSnapshot.feedback_for_coder) ||
      (typeof metadataRoot?.feedback_for_coder === 'string' && metadataRoot.feedback_for_coder) ||
      (typeof jsonSnapshot?.feedback_for_coder === 'string' && jsonSnapshot.feedback_for_coder) ||
      extractAssignment(content, 'feedback') ||
      extractAssignment(content, 'feedback_for_coder'),
    summary:
      (typeof metadataSnapshot?.summary === 'string' && metadataSnapshot.summary) ||
      (typeof metadataRoot?.summary === 'string' && metadataRoot.summary) ||
      (typeof jsonSnapshot?.summary === 'string' && jsonSnapshot.summary) ||
      extractAssignment(content, 'summary'),
    validationTier:
      (typeof metadataSnapshot?.validation_tier === 'string' && metadataSnapshot.validation_tier) ||
      (typeof metadataRoot?.validation_tier === 'string' && metadataRoot.validation_tier) ||
      (typeof jsonSnapshot?.validation_tier === 'string' && jsonSnapshot.validation_tier) ||
      extractAssignment(content, 'validation_tier'),
    qualityGateStatus:
      (typeof metadataSnapshot?.quality_gate_status === 'string' && metadataSnapshot.quality_gate_status) ||
      (typeof metadataRoot?.quality_gate_status === 'string' && metadataRoot.quality_gate_status) ||
      (typeof jsonSnapshot?.quality_gate_status === 'string' && jsonSnapshot.quality_gate_status) ||
      extractAssignment(content, 'quality_gate_status'),
    reportReadyHint:
      coerceBoolean(metadataSnapshot?.report_ready_hint) ??
      coerceBoolean(metadataRoot?.report_ready_hint) ??
      coerceBoolean(jsonSnapshot?.report_ready_hint) ??
      coerceBoolean(extractAssignment(content, 'report_ready_hint')),
    executionPolicyViolated:
      coerceBoolean(metadataSnapshot?.execution_policy_violated) ??
      coerceBoolean(metadataRoot?.execution_policy_violated) ??
      coerceBoolean(jsonSnapshot?.execution_policy_violated) ??
      coerceBoolean(extractAssignment(content, 'execution_policy_violated')),
    blockerFixMode:
      coerceBoolean(metadataSnapshot?.blocker_fix_mode) ??
      coerceBoolean(metadataRoot?.blocker_fix_mode) ??
      coerceBoolean(jsonSnapshot?.blocker_fix_mode) ??
      coerceBoolean(extractAssignment(content, 'blocker_fix_mode')),
    failureFingerprint:
      (typeof metadataSnapshot?.failure_fingerprint === 'string' && metadataSnapshot.failure_fingerprint) ||
      (typeof metadataRoot?.failure_fingerprint === 'string' && metadataRoot.failure_fingerprint) ||
      (typeof jsonSnapshot?.failure_fingerprint === 'string' && jsonSnapshot.failure_fingerprint) ||
      extractAssignment(content, 'failure_fingerprint'),
    failureRepeatCount:
      coerceNumber(metadataSnapshot?.failure_repeat_count) ??
      coerceNumber(metadataRoot?.failure_repeat_count) ??
      coerceNumber(jsonSnapshot?.failure_repeat_count) ??
      coerceNumber(extractAssignment(content, 'failure_repeat_count')),
    failureRootCause:
      (typeof metadataSnapshot?.failure_root_cause === 'string' && metadataSnapshot.failure_root_cause) ||
      (typeof metadataRoot?.failure_root_cause === 'string' && metadataRoot.failure_root_cause) ||
      (typeof jsonSnapshot?.failure_root_cause === 'string' && jsonSnapshot.failure_root_cause) ||
      extractAssignment(content, 'failure_root_cause'),
    iterationLabel: extractIterationLabel(content),
  };

  if (
    snapshot.executionSuccess === undefined &&
    snapshot.needsRework === undefined &&
    snapshot.readyForReport === undefined &&
    !snapshot.feedbackForCoder &&
    !snapshot.summary &&
    !snapshot.validationTier &&
    !snapshot.qualityGateStatus &&
    snapshot.reportReadyHint === undefined &&
    snapshot.executionPolicyViolated === undefined &&
    snapshot.blockerFixMode === undefined &&
    !snapshot.failureFingerprint &&
    snapshot.failureRepeatCount === undefined &&
    !snapshot.failureRootCause &&
    !snapshot.iterationLabel
  ) {
    return null;
  }

  return snapshot;
}
