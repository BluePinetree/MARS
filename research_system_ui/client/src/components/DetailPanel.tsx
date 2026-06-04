import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Streamdown } from 'streamdown';
import { getArtifactContent, streamArtifactContent } from '@/lib/api';
import {
  AlignLeft,
  BarChart3,
  Braces,
  Check,
  Code2,
  Copy,
  FileText,
  NotebookText,
  Wrench,
  X,
} from 'lucide-react';
import type { LogEvent } from '@/lib/types';
import { getAgentColor, formatTimestamp } from '@/lib/constants';
import { extractStatusSnapshot, inferRenderContent, type RenderDescriptor, type StatusSnapshot } from '@/lib/logEventContent';

interface DetailPanelProps {
  event: LogEvent | null;
  onClose: () => void;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function formatLabel(label: string): string {
  return label.replace(/_/g, ' ');
}

function stringifyValue(value: unknown): string {
  if (typeof value === 'string') {
    return value;
  }
  return JSON.stringify(value, null, 2);
}

function isTextArtifactPath(path: string): boolean {
  return /\.(log|txt|err|out|jsonl|csv|md|ya?ml|json)$/i.test(path);
}

function prefersLiveTail(path: string): boolean {
  return /\.(log|txt|err|out|jsonl|csv)$/i.test(path);
}

function renderTypeLabel(kind: RenderDescriptor['kind']): string {
  switch (kind) {
    case 'markdown':
      return 'Markdown';
    case 'json':
      return 'JSON';
    case 'code':
      return 'Code';
    default:
      return 'Text';
  }
}

function renderTypeIcon(kind: RenderDescriptor['kind']) {
  const iconProps = { size: 12, className: 'text-muted-foreground' };
  switch (kind) {
    case 'markdown':
      return <NotebookText {...iconProps} />;
    case 'json':
      return <Braces {...iconProps} />;
    case 'code':
      return <Code2 {...iconProps} />;
    default:
      return <AlignLeft {...iconProps} />;
  }
}

function hasVisibleStatus(snapshot: StatusSnapshot): boolean {
  return (
    snapshot.executionSuccess !== undefined ||
    snapshot.needsRework !== undefined ||
    snapshot.readyForReport !== undefined ||
    Boolean(snapshot.validationTier) ||
    Boolean(snapshot.qualityGateStatus) ||
    snapshot.reportReadyHint !== undefined ||
    snapshot.executionPolicyViolated !== undefined ||
    snapshot.blockerFixMode !== undefined ||
    Boolean(snapshot.failureFingerprint) ||
    snapshot.failureRepeatCount !== undefined ||
    Boolean(snapshot.failureRootCause) ||
    Boolean(snapshot.feedbackForCoder) ||
    Boolean(snapshot.summary)
  );
}

export default function DetailPanel({ event, onClose }: DetailPanelProps) {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [activeArtifactPath, setActiveArtifactPath] = useState<string | null>(null);
  const [artifactContent, setArtifactContent] = useState('');
  const [artifactResolvedPath, setArtifactResolvedPath] = useState('');
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  const [artifactTruncated, setArtifactTruncated] = useState(false);
  const metadataEntries = useMemo(
    () =>
      event?.metadata
        ? Object.entries(event.metadata).filter(([, value]) => value !== undefined && value !== null)
        : [],
    [event?.metadata],
  );

  const copyText = async (key: string, text: string) => {
    await navigator.clipboard.writeText(text);
    setCopiedKey(key);
    window.setTimeout(() => setCopiedKey((current) => (current === key ? null : current)), 1800);
  };

  useEffect(() => {
    setActiveArtifactPath(null);
    setArtifactContent('');
    setArtifactResolvedPath('');
    setArtifactLoading(false);
    setArtifactError(null);
    setArtifactTruncated(false);
  }, [event?.run_id, event?.timestamp]);

  useEffect(() => {
    if (!event?.run_id || !activeArtifactPath) {
      return;
    }

    let cancelled = false;
    let stopStream: (() => void) | null = null;

    const fetchArtifact = async () => {
      setArtifactLoading(true);
      setArtifactError(null);
      setArtifactContent('');

      try {
        const initial = await getArtifactContent(event.run_id, activeArtifactPath);
        if (cancelled) {
          return;
        }

        setArtifactResolvedPath(initial.resolved_path);
        setArtifactContent(initial.content || '');
        setArtifactTruncated(initial.truncated);
        setArtifactLoading(false);

        if (prefersLiveTail(activeArtifactPath)) {
          stopStream = streamArtifactContent(
            event.run_id,
            activeArtifactPath,
            {
              onEvent: (streamEvent) => {
                if (cancelled) {
                  return;
                }
                if (streamEvent.event_type === 'ARTIFACT_READY') {
                  if (typeof streamEvent.resolved_path === 'string') {
                    setArtifactResolvedPath(streamEvent.resolved_path);
                  }
                  void fetchArtifact();
                  return;
                }
              },
              onError: (error) => {
                if (cancelled) {
                  return;
                }
                const message = error instanceof Error ? error.message : 'artifact stream error';
                setArtifactError(message);
              },
            },
          );
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        const message = error instanceof Error ? error.message : 'artifact load error';
        setArtifactLoading(false);
        setArtifactError(message);
      }
    };

    void fetchArtifact();

    return () => {
      cancelled = true;
      stopStream?.();
    };
  }, [activeArtifactPath, event?.run_id]);

  if (!event) {
    return (
      <div className="h-full border-l border-border/50 bg-sidebar flex flex-col items-center justify-center px-6 text-center">
        <p className="text-xs font-mono text-muted-foreground">이벤트를 선택하면</p>
        <p className="text-xs font-mono text-muted-foreground">오른쪽 상세 정보가 표시됩니다.</p>
      </div>
    );
  }

  const color = getAgentColor(event.agent_name);
  const statusSnapshot = extractStatusSnapshot(event);
  const contentDescriptor = inferRenderContent(event.content || '', {
    eventType: event.event_type,
    languageHint: typeof event.metadata?.language === 'string' ? event.metadata.language : undefined,
    keyHint: event.event_type,
  });

  return (
    <div className="h-full border-l border-border/50 bg-sidebar flex flex-col min-w-0">
      <div className="px-4 py-3 border-b border-border/50 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <DetailIcon type={event.event_type} />
            <span className="text-xs font-semibold font-mono text-foreground">{event.event_type}</span>
            <span className="rounded-full border border-border/50 bg-background/50 px-2 py-0.5 text-[10px] font-mono text-muted-foreground">
              {renderTypeLabel(contentDescriptor.kind)}
            </span>
          </div>
          <p className="mt-2 text-sm font-semibold text-foreground">{event.agent_name || 'System'}</p>
          <p className="text-[11px] font-mono" style={{ color: color.textColor }}>
            {formatTimestamp(event.timestamp)}
          </p>
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
          <X size={14} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-5 min-w-0">
        {statusSnapshot && hasVisibleStatus(statusSnapshot) && <StatusSection snapshot={statusSnapshot} />}

        <section className="space-y-2">
          <SectionHeader title="기본 정보" icon={<FileText size={12} />} />
          <div className="rounded-xl border border-border/40 bg-background/30 p-3 space-y-2">
            <DetailRow label="시간" value={formatTimestamp(event.timestamp)} />
            {event.agent_name && (
              <DetailRow label="에이전트" value={event.agent_name} valueColor={color.textColor} />
            )}
            <DetailRow label="세션" value={event.session_id} />
            <DetailRow label="실행 ID" value={event.run_id} />
          </div>
        </section>

        {event.content && (
          <section className="space-y-2">
            <SectionHeader
              title="내용"
              icon={renderTypeIcon(contentDescriptor.kind)}
              action={
                <CopyButton
                  copied={copiedKey === 'content'}
                  onClick={() => copyText('content', event.content || '')}
                />
              }
            />
            <RichValueRenderer descriptor={contentDescriptor} rawValue={event.content} />
          </section>
        )}

        {metadataEntries.length > 0 && (
          <section className="space-y-2">
            <SectionHeader title="메타데이터" icon={<BarChart3 size={12} />} />
            <div className="space-y-3">
              {metadataEntries.map(([key, value]) =>
                Array.isArray(value) &&
                value.every((item) => typeof item === 'string') &&
                /artifact_paths|evidence_paths/i.test(key) ? (
                  <ArtifactPathsCard
                    key={key}
                    label={key}
                    value={value}
                    copied={copiedKey === key}
                    onCopy={() => copyText(key, stringifyValue(value))}
                    activeArtifactPath={activeArtifactPath}
                    onOpenArtifact={setActiveArtifactPath}
                  />
                ) : (
                  <MetadataCard
                    key={key}
                    label={key}
                    value={value}
                    copied={copiedKey === key}
                    onCopy={() => copyText(key, stringifyValue(value))}
                  />
                ),
              )}
            </div>
          </section>
        )}
        {activeArtifactPath && (
          <ArtifactViewerCard
            path={activeArtifactPath}
            resolvedPath={artifactResolvedPath}
            content={artifactContent}
            loading={artifactLoading}
            error={artifactError}
            truncated={artifactTruncated}
            copied={copiedKey === `artifact:${activeArtifactPath}`}
            onCopy={() => copyText(`artifact:${activeArtifactPath}`, artifactContent)}
            onClose={() => setActiveArtifactPath(null)}
          />
        )}
      </div>
    </div>
  );
}

function StatusSection({ snapshot }: { snapshot: StatusSnapshot }) {
  const badges: Array<{
    label: string;
    value: string;
    tone: 'success' | 'warning' | 'danger' | 'neutral';
  }> = [
    {
      label: '실행',
      value:
        snapshot.executionSuccess === undefined
          ? '미정'
          : snapshot.executionSuccess
            ? '성공'
            : '실패',
      tone:
        snapshot.executionSuccess === undefined
          ? 'neutral'
          : snapshot.executionSuccess
            ? 'success'
            : 'danger',
    },
    {
      label: '재작업',
      value:
        snapshot.needsRework === undefined ? '미정' : snapshot.needsRework ? '필요' : '불필요',
      tone:
        snapshot.needsRework === undefined
          ? 'neutral'
          : snapshot.needsRework
            ? 'warning'
            : 'success',
    },
    {
      label: '보고',
      value:
        snapshot.readyForReport === undefined ? '미정' : snapshot.readyForReport ? '가능' : '보류',
      tone:
        snapshot.readyForReport === undefined
          ? 'neutral'
          : snapshot.readyForReport
            ? 'success'
            : 'warning',
    },
    ...(snapshot.validationTier
      ? [
          {
            label: '검증',
            value: snapshot.validationTier,
            tone:
              snapshot.validationTier === 'reportable'
                ? 'success'
                : snapshot.validationTier === 'failed'
                  ? 'danger'
                  : 'warning',
          } as const,
        ]
      : []),
    ...(snapshot.blockerFixMode !== undefined
      ? [
          {
            label: 'blocker',
            value: snapshot.blockerFixMode ? 'fix mode' : 'normal',
            tone: snapshot.blockerFixMode ? ('danger' as const) : ('neutral' as const),
          },
        ]
      : []),
    ...(snapshot.failureRepeatCount !== undefined && snapshot.failureRepeatCount > 0
      ? [
          {
            label: 'repeat',
            value: String(snapshot.failureRepeatCount),
            tone: snapshot.failureRepeatCount >= 2 ? ('danger' as const) : ('warning' as const),
          },
        ]
      : []),
  ];

  return (
    <section className="space-y-2">
      <SectionHeader title="판정 요약" icon={<Wrench size={12} />} />
      <div className="rounded-xl border border-border/40 bg-background/30 p-3 space-y-3">
        <div className="flex flex-wrap gap-2">
          {snapshot.iterationLabel && (
            <Badge tone="neutral">
              <span>{snapshot.iterationLabel}</span>
            </Badge>
          )}
          {badges.map((badge) => (
            <Badge key={badge.label} tone={badge.tone}>
              <span className="text-muted-foreground">{badge.label}</span>
              <span>{badge.value}</span>
            </Badge>
          ))}
        </div>
        {snapshot.summary && (
          <p className="text-xs leading-relaxed text-foreground/85 whitespace-pre-wrap break-words">
            {snapshot.summary}
          </p>
        )}
        {(snapshot.failureRootCause || snapshot.failureFingerprint || snapshot.qualityGateStatus) && (
          <div className="rounded-lg border border-red-500/20 bg-red-500/8 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider font-mono text-red-300/80">blocker</p>
            {snapshot.failureRootCause && (
              <p className="mt-1 text-xs leading-relaxed text-foreground/85 whitespace-pre-wrap break-words">
                {snapshot.failureRootCause}
              </p>
            )}
            <div className="mt-2 flex flex-wrap gap-2">
              {snapshot.failureFingerprint && (
                <Badge tone="danger">
                  <span className="text-muted-foreground">fingerprint</span>
                  <span>{snapshot.failureFingerprint}</span>
                </Badge>
              )}
              {snapshot.qualityGateStatus && (
                <Badge tone={snapshot.qualityGateStatus === 'blocked' ? 'danger' : 'neutral'}>
                  <span className="text-muted-foreground">gate</span>
                  <span>{snapshot.qualityGateStatus}</span>
                </Badge>
              )}
              {snapshot.executionPolicyViolated !== undefined && (
                <Badge tone={snapshot.executionPolicyViolated ? 'danger' : 'neutral'}>
                  <span className="text-muted-foreground">policy</span>
                  <span>{snapshot.executionPolicyViolated ? 'violated' : 'ok'}</span>
                </Badge>
              )}
              {snapshot.reportReadyHint !== undefined && (
                <Badge tone={snapshot.reportReadyHint ? 'success' : 'warning'}>
                  <span className="text-muted-foreground">hint</span>
                  <span>{snapshot.reportReadyHint ? 'reportable' : 'hold'}</span>
                </Badge>
              )}
            </div>
          </div>
        )}
        {snapshot.feedbackForCoder && (
          <div className="rounded-lg border border-amber-500/20 bg-amber-500/8 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider font-mono text-amber-300/80">feedback</p>
            <p className="mt-1 text-xs leading-relaxed text-foreground/85 whitespace-pre-wrap break-words">
              {snapshot.feedbackForCoder}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

function MetadataCard({
  label,
  value,
  copied,
  onCopy,
}: {
  label: string;
  value: unknown;
  copied: boolean;
  onCopy: () => void;
}) {
  if (label === 'metrics' && isPlainObject(value)) {
    return (
      <div className="rounded-xl border border-border/40 bg-background/30 p-3 space-y-2">
        <SectionHeader title={formatLabel(label)} action={<CopyButton copied={copied} onClick={onCopy} />} />
        <div className="grid grid-cols-2 gap-2">
          {Object.entries(value).map(([metricKey, metricValue]) => (
            <div key={metricKey} className="rounded-lg border border-border/30 bg-muted/20 px-3 py-2">
              <p className="text-[10px] uppercase tracking-wider font-mono text-muted-foreground">
                {formatLabel(metricKey)}
              </p>
              <p className="mt-1 text-sm font-semibold font-mono text-emerald-300">
                {typeof metricValue === 'number'
                  ? metricValue > 0 && metricValue < 1
                    ? `${(metricValue * 100).toFixed(2)}%`
                    : metricValue.toFixed(4)
                  : String(metricValue)}
              </p>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (Array.isArray(value) && value.every((item) => typeof item === 'string')) {
    return (
      <div className="rounded-xl border border-border/40 bg-background/30 p-3 space-y-2">
        <SectionHeader
          title={`${formatLabel(label)} (${value.length})`}
          action={<CopyButton copied={copied} onClick={onCopy} />}
        />
        <div className="space-y-1.5">
          {value.map((entry, index) => (
            <div
              key={`${label}-${index}`}
              className="rounded-lg border border-border/30 bg-muted/20 px-3 py-2 text-[11px] font-mono text-foreground/85 break-all"
            >
              {entry}
            </div>
          ))}
        </div>
      </div>
    );
  }

  const descriptor = inferRenderContent(value, {
    keyHint: label,
    preferMarkdown: label.toLowerCase().includes('report'),
  });

  return (
    <div className="rounded-xl border border-border/40 bg-background/30 p-3 space-y-2">
      <SectionHeader
        title={formatLabel(label)}
        icon={renderTypeIcon(descriptor.kind)}
        action={<CopyButton copied={copied} onClick={onCopy} />}
      />
      <RichValueRenderer descriptor={descriptor} rawValue={value} compact />
    </div>
  );
}

function ArtifactPathsCard({
  label,
  value,
  copied,
  onCopy,
  activeArtifactPath,
  onOpenArtifact,
}: {
  label: string;
  value: string[];
  copied: boolean;
  onCopy: () => void;
  activeArtifactPath: string | null;
  onOpenArtifact: (path: string) => void;
}) {
  return (
    <div className="rounded-xl border border-border/40 bg-background/30 p-3 space-y-2">
      <SectionHeader
        title={`${formatLabel(label)} (${value.length})`}
        action={<CopyButton copied={copied} onClick={onCopy} />}
      />
      <div className="space-y-2">
        {value.map((entry, index) => {
          const openable = isTextArtifactPath(entry);
          const isActive = activeArtifactPath === entry;
          return (
            <div
              key={`${label}-${index}`}
              className="rounded-lg border border-border/30 bg-muted/20 px-3 py-2 space-y-2"
            >
              <div className="text-[11px] font-mono text-foreground/85 break-all">{entry}</div>
              {openable && (
                <div className="flex items-center justify-end gap-2">
                  <button
                    onClick={() => onOpenArtifact(entry)}
                    className="rounded-md border border-border/40 px-2 py-1 text-[10px] font-mono text-muted-foreground transition-colors hover:text-foreground hover:border-blue-200"
                  >
                    {isActive ? 'Viewing' : prefersLiveTail(entry) ? 'Open Live Tail' : 'Open File'}
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ArtifactViewerCard({
  path,
  resolvedPath,
  content,
  loading,
  error,
  truncated,
  copied,
  onCopy,
  onClose,
}: {
  path: string;
  resolvedPath: string;
  content: string;
  loading: boolean;
  error: string | null;
  truncated: boolean;
  copied: boolean;
  onCopy: () => void;
  onClose: () => void;
}) {
  const descriptor = inferRenderContent(content, {
    keyHint: path,
    languageHint: path.split('.').pop(),
  });

  return (
    <section className="space-y-2">
      <SectionHeader
        title="Live Artifact"
        icon={<FileText size={12} />}
        action={
          <div className="flex items-center gap-2">
            <CopyButton copied={copied} onClick={onCopy} />
            <button
              onClick={onClose}
              className="text-[10px] font-mono text-muted-foreground transition-colors hover:text-foreground"
            >
              Close
            </button>
          </div>
        }
      />
      <div className="rounded-xl border border-border/40 bg-background/30 p-3 space-y-3">
        <div className="space-y-1">
          <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">artifact path</p>
          <p className="text-[11px] font-mono text-foreground/85 break-all">{path}</p>
          {resolvedPath && (
            <>
              <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground pt-2">
                resolved path
              </p>
              <p className="text-[11px] font-mono text-foreground/70 break-all">{resolvedPath}</p>
            </>
          )}
        </div>

        {truncated && (
          <div className="rounded-lg border border-amber-500/20 bg-amber-500/8 px-3 py-2 text-[11px] font-mono text-amber-300">
            Initial load was truncated to the latest tail of the file.
          </div>
        )}

        {loading && (
          <div className="rounded-lg border border-border/30 bg-muted/20 px-3 py-2 text-[11px] font-mono text-muted-foreground">
            Loading artifact...
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-500/20 bg-red-500/8 px-3 py-2 text-[11px] font-mono text-red-300">
            {error}
          </div>
        )}

        {!loading && !error && (
          <RichValueRenderer descriptor={descriptor} rawValue={content} compact={false} />
        )}
      </div>
    </section>
  );
}

function RichValueRenderer({
  descriptor,
  rawValue,
  compact = false,
}: {
  descriptor: RenderDescriptor;
  rawValue: unknown;
  compact?: boolean;
}) {
  if (descriptor.kind === 'markdown') {
    return (
      <div className="rounded-xl border border-border/40 bg-background/20 px-3 py-3 overflow-x-auto">
        <Streamdown
          controls={false}
          className="text-sm leading-7 text-foreground [&_[data-streamdown='link']]:text-blue-600"
        >
          {descriptor.text}
        </Streamdown>
      </div>
    );
  }

  if (descriptor.kind === 'code' || descriptor.kind === 'json') {
    return (
      <div className="rounded-xl border border-border/40 overflow-hidden">
        <div className="flex items-center justify-between border-b border-border/30 bg-[#1E1E1E] px-3 py-2">
          <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
            {descriptor.language}
          </span>
          <span className="text-[10px] font-mono text-muted-foreground">
            {descriptor.kind === 'json' ? 'structured' : 'source'}
          </span>
        </div>
        <SyntaxHighlighter
          language={descriptor.language}
          style={vscDarkPlus}
          customStyle={{
            margin: 0,
            padding: compact ? '10px' : '12px',
            fontSize: compact ? '11px' : '12px',
            lineHeight: '1.6',
            background: '#111827',
            maxHeight: compact ? '320px' : 'none',
          }}
          showLineNumbers={!compact}
          wrapLongLines
          lineNumberStyle={{ color: '#556072', fontSize: '10px' }}
        >
          {descriptor.text}
        </SyntaxHighlighter>
      </div>
    );
  }

  return (
    <pre className="rounded-xl border border-border/40 bg-background/20 px-3 py-3 text-xs leading-relaxed text-foreground/85 whitespace-pre-wrap break-words font-mono overflow-x-auto">
      {typeof rawValue === 'string' ? rawValue : JSON.stringify(rawValue, null, 2)}
    </pre>
  );
}

function SectionHeader({
  title,
  icon,
  action,
}: {
  title: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex items-center gap-2 min-w-0">
        {icon}
        <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider truncate">{title}</p>
      </div>
      {action}
    </div>
  );
}

function CopyButton({ copied, onClick }: { copied: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1 text-[10px] font-mono text-muted-foreground hover:text-foreground transition-colors"
    >
      {copied ? <Check size={10} className="text-emerald-400" /> : <Copy size={10} />}
      {copied ? '복사됨' : '복사'}
    </button>
  );
}

function DetailRow({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <div className="flex items-start gap-3">
      <span className="text-[10px] font-mono text-muted-foreground shrink-0 w-16 pt-0.5">{label}</span>
      <span className="text-xs font-mono break-all text-foreground/90" style={{ color: valueColor || undefined }}>
        {value}
      </span>
    </div>
  );
}

function Badge({
  children,
  tone,
}: {
  children: ReactNode;
  tone: 'success' | 'warning' | 'danger' | 'neutral';
}) {
  const toneClass =
    tone === 'success'
      ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
      : tone === 'warning'
        ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
        : tone === 'danger'
          ? 'border-red-500/30 bg-red-500/10 text-red-300'
          : 'border-border/50 bg-muted/20 text-foreground/80';

  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-mono ${toneClass}`}>
      {children}
    </span>
  );
}

function DetailIcon({ type }: { type: string }) {
  const iconProps = { size: 12, className: 'text-muted-foreground' };
  switch (type) {
    case 'CODE_BLOCK':
      return <Code2 {...iconProps} />;
    case 'EXPERIMENT_RESULT':
      return <BarChart3 {...iconProps} />;
    case 'TOOL_CALL':
    case 'TOOL_RESULT':
      return <Wrench {...iconProps} />;
    default:
      return <FileText {...iconProps} />;
  }
}
