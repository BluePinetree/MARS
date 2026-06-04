import { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronDown, ChevronRight, Brain,
  FileCode, FileSearch, FolderTree, CheckSquare, Package,
  Terminal, BarChart2, BookOpen, Wrench,
  FlaskConical, CheckCircle2, AlertTriangle, Play, Square, ArrowRight,
} from 'lucide-react';
import type { LogEvent } from '@/lib/types';
import type { AgentColor } from '@/lib/types';
import { getAgentColor, formatTimestamp } from '@/lib/constants';
import { extractIterationLabel, extractStatusSnapshot } from '@/lib/logEventContent';

interface AgentConversationProps {
  events: LogEvent[];
  onEventClick?: (event: LogEvent) => void;
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface ToolCallPair {
  call: LogEvent;
  result?: LogEvent;
}

interface AgentTurn {
  id: string;
  speaker: string;
  color: AgentColor;
  messages: LogEvent[];
  thinkingEvents: LogEvent[];
  toolCalls: ToolCallPair[];
  firstTimestamp: string;
  lastTimestamp: string;
}

type TimelineItem =
  | { kind: 'turn'; turn: AgentTurn }
  | { kind: 'system'; event: LogEvent }
  | { kind: 'iteration'; label: string };

// ─── Speaker inference (V3 agent names) ──────────────────────────────────────

const ROLE_ALIAS: Record<string, string> = {
  Coder: 'Research Code Engineer',
  Writer: 'Research Paper Writer',
  Analyzer: 'Result Analyzer',
  Planner: 'AI Research Planner',
  Designer: 'Experiment Designer',
  Executor: 'Experiment Executor',
};

function normalizeAgentName(name?: string): string {
  if (!name) return 'System';
  return ROLE_ALIAS[name] || name;
}

function extractActionName(content?: string): string {
  if (!content) return '';
  const match = content.match(/Action:\s*([a-zA-Z0-9_]+)/);
  return match ? match[1] : '';
}

function detectSpeakerFromTaskText(lower: string): string | null {
  if (!lower.includes('task complete:')) return null;
  if (lower.includes('research plan')) return 'AI Research Planner';
  if (lower.includes('experiment design')) return 'Experiment Designer';
  if (lower.includes('implement or revise executable experiment code') || lower.includes('executable experiment code for iteration')) return 'Research Code Engineer';
  if (lower.includes('execute the generated code for iteration')) return 'Experiment Executor';
  if (lower.includes('analyze the latest execution result')) return 'Result Analyzer';
  if (lower.includes('report') && lower.includes('write')) return 'Research Paper Writer';
  return null;
}

function detectSpeakerFromPhase(lower: string, event: LogEvent): string | null {
  const phaseName = String(event.metadata?.phase_name || '').toLowerCase();
  const src = `${lower} ${phaseName}`;
  if (src.includes('research planning')) return 'AI Research Planner';
  if (src.includes('experiment design')) return 'Experiment Designer';
  if (src.includes('code generation')) return 'Research Code Engineer';
  if (src.includes('execution')) return 'Experiment Executor';
  if (src.includes('analysis')) return 'Result Analyzer';
  if (src.includes('report writing') || src.includes('writing')) return 'Research Paper Writer';
  return null;
}

function detectSpeakerFromThinking(lower: string): string | null {
  const action = extractActionName(lower);
  if (action === 'WorkspaceWriteTool') return 'Research Code Engineer';
  if (action === 'RunCommandTool') return 'Experiment Executor';
  if (action === 'WorkspaceReadTool' || action === 'ReadResultTool') return 'Result Analyzer';
  if (lower.includes('final answer') && lower.includes('main_experiment.py')) return 'Research Code Engineer';
  if (lower.includes('decide rework') || lower.includes('failure evidence')) return 'Result Analyzer';
  return null;
}

const GENERIC_NAMES = new Set(['System', 'Agent', 'agent', '']);

function inferSpeaker(event: LogEvent, lastNonSystem: string | null): string {
  const explicit = normalizeAgentName(event.agent_name);
  if (!GENERIC_NAMES.has(explicit)) return explicit;

  const lower = (event.content || '').toLowerCase();

  if (event.event_type === 'EXPERIMENT_START') return 'Experiment Executor';
  if (event.event_type === 'EXPERIMENT_RESULT') return 'Result Analyzer';
  if (event.event_type === 'PHASE_COMPLETE') {
    const f = detectSpeakerFromPhase(lower, event);
    if (f) return f;
  }
  if (event.event_type === 'TOOL_CALL' || event.event_type === 'TOOL_RESULT') {
    const toolName = String(event.metadata?.tool_name || '').toLowerCase();
    if (toolName.includes('workspacewrite')) return 'Research Code Engineer';
    if (toolName.includes('runcommand')) return 'Experiment Executor';
    if (toolName.includes('workspaceread') || toolName.includes('readresult')) return 'Result Analyzer';
    if (toolName.includes('writereport')) return 'Research Paper Writer';
  }
  if (event.event_type === 'AGENT_THINKING') {
    const f = detectSpeakerFromThinking(lower);
    if (f) return f;
  }
  if (event.event_type === 'AGENT_MESSAGE') {
    // Structured agent_tag → deterministic speaker routing
    const tag = String((event.metadata as Record<string, unknown>)?.agent_tag ?? '');
    if (tag === 'FileCoder') return 'Research Code Engineer';
    if (tag === 'DirectExec' || tag === 'Training') return 'Experiment Executor';
    if (tag === 'DirectAnalyze') return 'Result Analyzer';

    const f = detectSpeakerFromTaskText(lower);
    if (f) return f;
    if (lower.includes('file saved:') && lower.includes('generated_code')) return 'Research Code Engineer';
    if (lower.includes('iteration') && lower.includes('decision:')) return 'Result Analyzer';
    if (lower.includes('report.md') || lower.includes('research paper writer')) return 'Research Paper Writer';
    if (lower.includes('starting execution of the canonical experiment')) return 'Experiment Executor';
  }
  if (lastNonSystem && event.event_type !== 'SYSTEM_START' && event.event_type !== 'SYSTEM_END') return lastNonSystem;
  return 'System';
}

// ─── Noise filter ─────────────────────────────────────────────────────────────

// Matches raw CrewAI internal Python repr that should never reach the UI.
// Covers both old events already in DB and any future leakage.
const _INTERNAL_REPR_RE = /^\[.*?\]\s*(ToolResult\(|AgentFinish\(|AgentAction\(|CrewAgent)/i;
// Matches old-style "[agent] Tool: X — [{...}]" format (array JSON input = raw dump)
const _RAW_TOOL_ARRAY_RE = /^\[.*?\]\s*Tool:\s+\S+\s+[—-]\s+\[?\{/;

function isNoisyEvent(event: LogEvent): boolean {
  if (event.event_type !== 'AGENT_MESSAGE') return false;
  const c = event.content ?? '';
  return _INTERNAL_REPR_RE.test(c) || _RAW_TOOL_ARRAY_RE.test(c);
}

// ─── Timeline builder ─────────────────────────────────────────────────────────

// Speakers that carry no identity information — treated same as System for grouping
const EMPTY_SPEAKERS = new Set(['System', 'Agent', '']);

const SYSTEM_EVENT_TYPES = new Set([
  'SYSTEM_START', 'SYSTEM_END', 'PHASE_COMPLETE',
  'EXPERIMENT_START', 'EXPERIMENT_RESULT', 'WORKSPACE_GENERATION_START',
]);

function buildTimeline(events: LogEvent[]): TimelineItem[] {
  const items: TimelineItem[] = [];
  let currentTurn: AgentTurn | null = null;
  let lastNonSystem: string | null = null;
  let lastIterLabel: string | null = null;

  const flushTurn = () => {
    if (currentTurn && (currentTurn.messages.length + currentTurn.toolCalls.length + currentTurn.thinkingEvents.length > 0)) {
      items.push({ kind: 'turn', turn: currentTurn });
    }
    currentTurn = null;
  };

  for (const event of events) {
    // Drop raw CrewAI internal repr events (old DB entries + future leakage)
    if (isNoisyEvent(event)) continue;

    // Iteration markers
    const iterLabel = extractIterationLabel(event.content || '');
    if (iterLabel && iterLabel !== lastIterLabel) {
      lastIterLabel = iterLabel;
      flushTurn();
      items.push({ kind: 'iteration', label: iterLabel });
    }

    // System events → standalone dividers
    if (SYSTEM_EVENT_TYPES.has(event.event_type)) {
      flushTurn();
      items.push({ kind: 'system', event });
      continue;
    }

    const speaker = inferSpeaker(event, lastNonSystem);
    if (!EMPTY_SPEAKERS.has(speaker)) lastNonSystem = speaker;

    // TOOL_RESULT: attach to the last pending call in current turn
    if (event.event_type === 'TOOL_RESULT') {
      if (currentTurn) {
        const pairs = currentTurn.toolCalls;
        const last = pairs[pairs.length - 1];
        if (last && !last.result) last.result = event;
        currentTurn.lastTimestamp = event.timestamp;
      }
      // Orphaned TOOL_RESULT (no current turn) → skip
      continue;
    }

    // Skip truly empty AGENT_MESSAGE events
    if (event.event_type === 'AGENT_MESSAGE' && !event.content?.trim()) {
      continue;
    }

    // Resolve effective speaker for grouping
    const effectiveSpeaker = EMPTY_SPEAKERS.has(speaker) ? (lastNonSystem || 'System') : speaker;

    // Start new turn if speaker changed
    if (!currentTurn || currentTurn.speaker !== effectiveSpeaker) {
      flushTurn();
      currentTurn = {
        id: `${effectiveSpeaker}-${event.timestamp}`,
        speaker: effectiveSpeaker,
        color: getAgentColor(effectiveSpeaker),
        messages: [],
        thinkingEvents: [],
        toolCalls: [],
        firstTimestamp: event.timestamp,
        lastTimestamp: event.timestamp,
      };
    }

    currentTurn.lastTimestamp = event.timestamp;

    // AGENT_MESSAGE with tool_name metadata = clean tool call from new callbacks
    const isToolCallMsg = event.event_type === 'AGENT_MESSAGE' && !!event.metadata?.tool_name;

    if (event.event_type === 'TOOL_CALL' || isToolCallMsg) {
      currentTurn.toolCalls.push({ call: event, result: undefined });
    } else if (event.event_type === 'AGENT_THINKING') {
      currentTurn.thinkingEvents.push(event);
    } else {
      currentTurn.messages.push(event);
    }
  }

  flushTurn();
  return items;
}

// ─── Tool icon ────────────────────────────────────────────────────────────────

function ToolIcon({ toolName, size = 11 }: { toolName: string; size?: number }) {
  const n = (toolName || '').toLowerCase();
  const p = { size, className: 'shrink-0' };
  if (n.includes('writereport')) return <BookOpen {...p} />;
  if (n.includes('write')) return <FileCode {...p} />;
  if (n.includes('readresult')) return <BarChart2 {...p} />;
  if (n.includes('read')) return <FileSearch {...p} />;
  if (n.includes('list')) return <FolderTree {...p} />;
  if (n.includes('syntax')) return <CheckSquare {...p} />;
  if (n.includes('import')) return <Package {...p} />;
  if (n.includes('command') || n.includes('run')) return <Terminal {...p} />;
  return <Wrench {...p} />;
}

// ─── ToolCallRow ──────────────────────────────────────────────────────────────

function ToolCallRow({ pair, onClickDetail }: { pair: ToolCallPair; onClickDetail?: (e: LogEvent) => void }) {
  const [expanded, setExpanded] = useState(false);
  const toolName = String(pair.call.metadata?.tool_name || 'Tool');
  const toolInput = pair.call.metadata?.tool_input as Record<string, unknown> | undefined;
  const success = pair.result ? pair.result.metadata?.success !== false : undefined;
  const isPending = !pair.result;

  const descriptor = String(
    toolInput?.path ?? toolInput?.command ?? toolInput?.module_name ?? toolInput?.output_path ?? ''
  ).replace(/.*[\\/]/, '').slice(0, 50);

  return (
    <div className="font-mono text-[11px]">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 w-full text-left py-[3px] px-1.5 rounded hover:bg-black/[0.04] transition-colors"
      >
        <span className="text-muted-foreground/30 w-3 flex justify-center">
          {expanded ? <ChevronDown size={9} /> : <ChevronRight size={9} />}
        </span>
        <span className="text-muted-foreground/40">
          <ToolIcon toolName={toolName} />
        </span>
        <span className="text-muted-foreground/70 font-medium">{toolName}</span>
        {descriptor && (
          <span className="text-muted-foreground/40 truncate max-w-[180px]">· {descriptor}</span>
        )}
        <span className="ml-auto text-[10px]">
          {isPending && <span className="text-amber-600/80 animate-pulse">실행 중</span>}
          {!isPending && success === true && <span className="text-emerald-600">✓</span>}
          {!isPending && success === false && <span className="text-red-600">✗</span>}
        </span>
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
            className="overflow-hidden"
          >
            <div
              className="ml-5 my-1 rounded-md bg-background/70 border border-border/25 px-2.5 py-2 space-y-1 cursor-pointer hover:border-border/40 transition-colors"
              onClick={() => onClickDetail?.(pair.call)}
            >
              {toolInput && Object.entries(toolInput).map(([k, v]) => (
                <div key={k} className="flex gap-2 leading-relaxed">
                  <span className="text-muted-foreground/40 shrink-0">{k}:</span>
                  <span className="text-muted-foreground/70 break-all">
                    {String(v).length > 300 ? `${String(v).slice(0, 300)}…` : String(v)}
                  </span>
                </div>
              ))}
              {pair.result && (
                <div className="border-t border-border/25 mt-1.5 pt-1.5 space-y-1">
                  <span className={`text-[10px] font-semibold ${success ? 'text-emerald-700' : 'text-red-600'}`}>
                    {success ? '▸ 완료' : '▸ 실패'}
                  </span>
                  {pair.result.content && (
                    <div className="text-muted-foreground/55 whitespace-pre-wrap break-words max-h-28 overflow-y-auto leading-relaxed">
                      {pair.result.content.length > 600
                        ? `${pair.result.content.slice(0, 600)}…`
                        : pair.result.content}
                    </div>
                  )}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ─── AgentTurnCard ────────────────────────────────────────────────────────────

function AgentTurnCard({ turn, onEventClick }: { turn: AgentTurn; onEventClick?: (e: LogEvent) => void }) {
  const { color, speaker } = turn;
  const [showThinking, setShowThinking] = useState(false);
  const hasTools = turn.toolCalls.length > 0;
  const hasThinking = turn.thinkingEvents.length > 0;
  const hasMessages = turn.messages.length > 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: 'easeOut' }}
      className="relative pl-3 py-1"
      style={{ borderLeft: `2px solid ${color.borderColor}60` }}
    >
      {/* Agent header */}
      <div className="flex items-center gap-2 mb-2">
        <div
          className="w-[18px] h-[18px] rounded-full flex items-center justify-center text-[9px] font-bold shrink-0"
          style={{ backgroundColor: color.bgColor, color: color.textColor, border: `1px solid ${color.borderColor}` }}
        >
          {speaker.charAt(0)}
        </div>
        <span className="text-[11px] font-semibold font-mono" style={{ color: color.textColor }}>
          {speaker}
        </span>
        <span className="text-[10px] font-mono text-muted-foreground/40 ml-auto">
          {formatTimestamp(turn.firstTimestamp)}
        </span>
      </div>

      {/* Thinking toggle */}
      {hasThinking && (
        <div className="mb-2 ml-1">
          <button
            onClick={() => setShowThinking(!showThinking)}
            className="flex items-center gap-1.5 text-[10px] text-muted-foreground/40 hover:text-muted-foreground/70 transition-colors"
          >
            <Brain size={9} />
            <span>{showThinking ? '사고 과정 접기' : `사고 과정 (${turn.thinkingEvents.length})`}</span>
            {showThinking ? <ChevronDown size={9} /> : <ChevronRight size={9} />}
          </button>
          <AnimatePresence>
            {showThinking && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="overflow-hidden"
              >
                <div className="mt-1.5 ml-3 pl-2 border-l border-border/20 space-y-1.5 max-h-40 overflow-y-auto">
                  {turn.thinkingEvents.map((e, i) => (
                    <p key={i} className="text-[10px] text-muted-foreground/40 italic leading-relaxed">
                      {(e.content || '').slice(0, 400)}
                      {(e.content?.length ?? 0) > 400 ? '…' : ''}
                    </p>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {/* Messages */}
      {hasMessages && (
        <div className="space-y-1.5 mb-2">
          {turn.messages.map((msg, i) => (
            <MessageBubble key={i} event={msg} color={color} onClick={() => onEventClick?.(msg)} />
          ))}
        </div>
      )}

      {/* Tool calls */}
      {hasTools && (
        <div className="ml-1 space-y-0.5">
          {turn.toolCalls.map((pair, i) => (
            <ToolCallRow key={i} pair={pair} onClickDetail={onEventClick} />
          ))}
        </div>
      )}
    </motion.div>
  );
}

// ─── JSON detection & structured renderers ────────────────────────────────────

function tryParseJson(text: string): Record<string, unknown> | null {
  const trimmed = text.trim();
  if (!trimmed.startsWith('{')) return null;

  // 1. Direct parse
  try {
    const parsed = JSON.parse(trimmed);
    if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) return parsed;
  } catch { /* fall through */ }

  // 2. Extract largest {...} substring
  const start = trimmed.indexOf('{');
  const end = trimmed.lastIndexOf('}');
  if (start >= 0 && end > start) {
    try {
      const parsed = JSON.parse(trimmed.slice(start, end + 1));
      if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) return parsed;
    } catch { /* fall through */ }
  }

  // 3. Truncated JSON recovery — append missing closing braces/brackets
  if (start >= 0) {
    let depth = 0;
    let inString = false;
    let escaped = false;
    for (const ch of trimmed) {
      if (escaped) { escaped = false; continue; }
      if (ch === '\\' && inString) { escaped = true; continue; }
      if (ch === '"') { inString = !inString; continue; }
      if (inString) continue;
      if (ch === '{' || ch === '[') depth++;
      else if (ch === '}' || ch === ']') depth--;
    }
    if (depth > 0) {
      const suffix = '}'.repeat(depth);
      try {
        const parsed = JSON.parse(trimmed + suffix);
        if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) return parsed;
      } catch { /* fall through */ }
    }
  }

  return null;
}

type JsonOutputType = 'planner' | 'designer' | 'analyzer' | 'generic';

function detectJsonType(obj: Record<string, unknown>): JsonOutputType {
  if ('problem_statement' in obj && 'research_questions' in obj) return 'planner';
  if ('workspace_structure' in obj && 'experiment_family' in obj) return 'designer';
  if ('execution_success' in obj && 'should_continue' in obj) return 'analyzer';
  return 'generic';
}

function Pill({ text, variant = 'default' }: { text: string; variant?: 'success' | 'warning' | 'error' | 'info' | 'default' }) {
  const cls = {
    success: 'bg-emerald-50 border-emerald-200 text-emerald-700',
    warning: 'bg-amber-50 border-amber-200 text-amber-700',
    error: 'bg-red-50 border-red-200 text-red-600',
    info: 'bg-blue-50 border-blue-200 text-blue-600',
    default: 'bg-muted/30 border-border/40 text-muted-foreground',
  }[variant];
  return <span className={`inline-block text-[10px] font-mono px-1.5 py-0.5 rounded border ${cls}`}>{text}</span>;
}

function BulletList({ items, label }: { items: string[]; label: string }) {
  if (!items.length) return null;
  return (
    <div className="space-y-0.5">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/50">{label}</div>
      <ul className="space-y-0.5 pl-0">
        {items.map((item, i) => (
          <li key={i} className="flex gap-1.5 text-[12px] text-foreground/80 leading-snug">
            <span className="text-muted-foreground/30 shrink-0 mt-px">·</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function PlannerOutputCard({ obj }: { obj: Record<string, unknown> }) {
  const questions = (obj.research_questions as string[] | undefined) ?? [];
  const hypotheses = (obj.hypotheses as string[] | undefined) ?? [];
  const criteria = (obj.success_criteria as string[] | undefined) ?? [];
  const risks = (obj.risks as { risk: string; mitigation: string }[] | undefined) ?? [];
  const profile = obj.recommended_profile as string | undefined;
  const nextInputs = obj.next_stage_inputs as Record<string, string> | undefined;

  return (
    <div className="space-y-2.5 text-[12px]">
      {!!obj.problem_statement && (
        <div className="rounded-md bg-blue-50/60 border border-blue-100 px-2.5 py-2 text-[12px] text-blue-900/80 leading-snug">
          {String(obj.problem_statement)}
        </div>
      )}
      <BulletList items={questions} label="연구 질문" />
      <BulletList items={hypotheses} label="가설" />
      <BulletList items={criteria} label="성공 기준" />
      {risks.length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/50">리스크</div>
          {risks.map((r, i) => (
            <div key={i} className="flex gap-1.5 text-[12px] leading-snug">
              <span className="text-amber-500 shrink-0">⚠</span>
              <span className="text-foreground/80">{r.risk}</span>
              {r.mitigation && <span className="text-muted-foreground/50">→ {r.mitigation}</span>}
            </div>
          ))}
        </div>
      )}
      <div className="flex flex-wrap gap-1.5 pt-0.5">
        {profile && <Pill text={`프로필: ${profile}`} variant="info" />}
        {nextInputs?.primary_metric && <Pill text={`지표: ${nextInputs.primary_metric}`} variant="default" />}
      </div>
    </div>
  );
}

function DesignerOutputCard({ obj }: { obj: Record<string, unknown> }) {
  const ws = obj.workspace_structure as Record<string, unknown> | undefined;
  const files = (ws?.files as { path: string; responsibility?: string; mutable?: boolean }[] | undefined) ?? [];
  const mutableFiles = files.filter(f => f.mutable !== false);
  const evalProtocol = obj.evaluation_protocol as Record<string, unknown> | undefined;
  const secondaryMetrics = (evalProtocol?.secondary_metrics as string[] | undefined) ?? [];

  return (
    <div className="space-y-2.5 text-[12px]">
      {!!obj.experiment_family && (
        <div className="font-semibold text-foreground/90">{String(obj.experiment_family)}</div>
      )}
      {!!evalProtocol && (
        <div className="flex flex-wrap gap-1.5">
          {!!evalProtocol.primary_metric && <Pill text={`주요 지표: ${String(evalProtocol.primary_metric)}`} variant="info" />}
          {secondaryMetrics.map((m, i) => <Pill key={i} text={m} variant="default" />)}
        </div>
      )}
      {!!ws?.scaffold_type && (
        <Pill text={`스캐폴드: ${String(ws.scaffold_type)}`} variant="info" />
      )}
      {mutableFiles.length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/50">
            생성 파일 ({mutableFiles.length}개)
          </div>
          <div className="grid grid-cols-1 gap-0.5">
            {mutableFiles.map((f, i) => (
              <div key={i} className="flex gap-2 items-start">
                <span className="text-[10px] font-mono text-blue-600/70 shrink-0 mt-0.5">{f.path}</span>
                {f.responsibility && (
                  <span className="text-[11px] text-muted-foreground/50 leading-snug">{f.responsibility}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function AnalyzerOutputCard({ obj }: { obj: Record<string, unknown> }) {
  const success = obj.execution_success as boolean | undefined;
  const metric = obj.primary_metric_value as number | undefined;
  const diagnosis = obj.failure_diagnosis as string | undefined;
  const fixInstructions = (obj.fix_instructions as string[] | undefined) ?? [];
  const shouldContinue = obj.should_continue as boolean | undefined;
  const repairActions = (obj.repair_actions as { path: string; symbol?: string; reason?: string }[] | undefined) ?? [];

  return (
    <div className="space-y-2.5 text-[12px]">
      <div className="flex flex-wrap gap-2 items-center">
        <Pill text={success ? '✓ 실행 성공' : '✗ 실행 실패'} variant={success ? 'success' : 'error'} />
        {metric !== undefined && (
          <Pill
            text={`정확도: ${typeof metric === 'number' && metric <= 1 ? `${(metric * 100).toFixed(2)}%` : String(metric)}`}
            variant="info"
          />
        )}
        {shouldContinue !== undefined && (
          <Pill text={shouldContinue ? '반복 계속' : '반복 종료'} variant={shouldContinue ? 'warning' : 'success'} />
        )}
      </div>
      {diagnosis && (
        <div className="rounded-md bg-red-50/60 border border-red-100 px-2.5 py-2 text-[12px] text-red-800/80 leading-snug">
          {diagnosis}
        </div>
      )}
      <BulletList items={fixInstructions} label="수정 지침" />
      {repairActions.length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/50">수정 대상</div>
          {repairActions.map((a, i) => (
            <div key={i} className="flex gap-1.5 items-center text-[11px]">
              <span className="font-mono text-blue-600/70">{a.path}</span>
              {a.symbol && <span className="text-muted-foreground/40">·{a.symbol}</span>}
              {a.reason && <span className="text-muted-foreground/50 truncate">{a.reason}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function GenericJsonCard({ obj }: { obj: Record<string, unknown> }) {
  const entries = Object.entries(obj).slice(0, 12);
  return (
    <div className="space-y-1 text-[12px] font-mono">
      {entries.map(([k, v]) => {
        const val = typeof v === 'object' ? JSON.stringify(v, null, 0) : String(v);
        const short = val.length > 120 ? `${val.slice(0, 120)}…` : val;
        return (
          <div key={k} className="flex gap-2 items-start">
            <span className="text-muted-foreground/40 shrink-0">{k}:</span>
            <span className="text-foreground/75 break-words">{short}</span>
          </div>
        );
      })}
    </div>
  );
}

// ─── FileCoder inline result ──────────────────────────────────────────────────

const _FILE_WRITE_RE = /OK:\s*wrote\s+(\d+)\s+lines?\s+to\s+([\w./\\-]+)/i;
const _FILE_EDIT_RE = /OK:\s*replaced\s+\d+\s+chars?\s+with\s+\d+\s+chars?\s+in\s+([\w./\\-]+)/i;
const _RUN_OK_RE = /"return_code":\s*0/;
const _RUN_FAIL_RE = /"return_code":\s*(-?[1-9]\d*)/;
const _ENV_ERROR_RE = /"env_error"/;

function FileCoderResultBadge({ content }: { content: string }) {
  const writeMatch = content.match(_FILE_WRITE_RE);
  if (writeMatch) {
    return (
      <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-2 py-0.5">
        <CheckCircle2 size={10} />
        {writeMatch[2].split(/[/\\]/).pop()} · {writeMatch[1]} lines
      </span>
    );
  }
  const editMatch = content.match(_FILE_EDIT_RE);
  if (editMatch) {
    return (
      <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-blue-700 bg-blue-50 border border-blue-200 rounded px-2 py-0.5">
        ✎ {editMatch[1].split(/[/\\]/).pop()} patched
      </span>
    );
  }
  if (_ENV_ERROR_RE.test(content)) {
    return (
      <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-0.5">
        ⚠ Environment error (DLL/CUDA) — code OK
      </span>
    );
  }
  if (_RUN_OK_RE.test(content)) {
    return (
      <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-2 py-0.5">
        <CheckCircle2 size={10} /> import OK
      </span>
    );
  }
  const failMatch = content.match(_RUN_FAIL_RE);
  if (failMatch) {
    return (
      <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-red-700 bg-red-50 border border-red-200 rounded px-2 py-0.5">
        ✗ exit {failMatch[1]}
      </span>
    );
  }
  return null;
}

// Detect if content is a raw RunCommandTool JSON result
function isRunCommandResult(content: string): boolean {
  return content.trim().startsWith('{"return_code"');
}

function SmartMessageContent({ content }: { content: string }) {
  // RunCommandTool / WorkspaceWriteTool / FileEditTool results → compact badge
  const badge = FileCoderResultBadge({ content });
  if (badge && (isRunCommandResult(content) || _FILE_WRITE_RE.test(content) || _FILE_EDIT_RE.test(content))) {
    return <div>{badge}</div>;
  }

  const json = tryParseJson(content);
  if (!json) {
    return <p className="text-foreground/90 whitespace-pre-wrap break-words text-[13px] leading-relaxed">{content}</p>;
  }
  const type = detectJsonType(json);
  return (
    <div>
      {type === 'planner' && <PlannerOutputCard obj={json} />}
      {type === 'designer' && <DesignerOutputCard obj={json} />}
      {type === 'analyzer' && <AnalyzerOutputCard obj={json} />}
      {type === 'generic' && <GenericJsonCard obj={json} />}
    </div>
  );
}

// ─── Agent Tag Card Components ────────────────────────────────────────────────

function AgentTagBadge({ tag, color }: { tag: string; color: string }) {
  return (
    <span
      className="inline-flex items-center font-mono text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded mr-1.5 shrink-0"
      style={{ backgroundColor: `${color}18`, color, border: `1px solid ${color}35` }}
    >
      {tag}
    </span>
  );
}

function DirectExecRunningCard({ meta }: { meta: Record<string, unknown> }) {
  const iteration = Number(meta.iteration ?? 1);
  const attempt = Number(meta.attempt ?? 1);
  return (
    <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
      <AgentTagBadge tag="exec" color="#6366f1" />
      <span className="text-foreground/80">실험 실행 중</span>
      <span className="font-mono text-[11px] text-slate-400">iter {iteration} · attempt {attempt}</span>
      <motion.div
        className="w-1.5 h-1.5 rounded-full bg-indigo-400"
        animate={{ opacity: [1, 0.3, 1] }}
        transition={{ repeat: Infinity, duration: 1.2 }}
      />
    </div>
  );
}

function DirectExecResultCard({ meta }: { meta: Record<string, unknown> }) {
  const rc = Number(meta.rc ?? -1);
  const duration = Number(meta.duration ?? 0);
  const hasResult = Boolean(meta.result_json_present);
  const ok = rc === 0;
  return (
    <div className="flex items-center flex-wrap gap-2">
      <AgentTagBadge tag="exec" color="#6366f1" />
      <span className={`inline-flex items-center gap-1 font-mono text-[11px] px-1.5 py-0.5 rounded border ${ok ? 'text-emerald-700 bg-emerald-50 border-emerald-200' : 'text-red-700 bg-red-50 border-red-200'}`}>
        {ok ? <CheckCircle2 size={10} /> : '✗'} RC {rc}
      </span>
      <span className="font-mono text-[11px] text-muted-foreground px-1.5 py-0.5 rounded bg-muted border border-border">
        ⏱ {duration}s
      </span>
      <span className={`font-mono text-[11px] px-1.5 py-0.5 rounded border ${hasResult ? 'text-emerald-700 bg-emerald-50 border-emerald-200' : 'text-amber-700 bg-amber-50 border-amber-200'}`}>
        📄 {hasResult ? 'result.json 있음' : 'result.json 없음'}
      </span>
    </div>
  );
}

function DirectAnalyzeCard({ meta }: { meta: Record<string, unknown> }) {
  const success = Boolean(meta.success);
  const raw = meta.metric;
  const metric = raw !== undefined && raw !== null ? String(raw) : '—';
  const shouldContinue = Boolean(meta.should_continue);
  return (
    <div className="flex items-center flex-wrap gap-2">
      <AgentTagBadge tag="analyze" color="#0d9488" />
      <span className={`font-mono text-[11px] px-1.5 py-0.5 rounded border ${success ? 'text-emerald-700 bg-emerald-50 border-emerald-200' : 'text-red-700 bg-red-50 border-red-200'}`}>
        {success ? '✓' : '✗'} {success ? '성공' : '실패'}
      </span>
      <span className="font-mono text-[11px] px-1.5 py-0.5 rounded border border-slate-200 bg-slate-50 text-slate-600">
        metric: {metric}
      </span>
      <span className={`font-mono text-[11px] px-1.5 py-0.5 rounded border ${shouldContinue ? 'text-blue-700 bg-blue-50 border-blue-200' : 'text-slate-600 bg-slate-50 border-slate-200'}`}>
        {shouldContinue ? '→ 계속' : '⏹ 완료'}
      </span>
    </div>
  );
}

function FileCoderTagCard({ content, meta }: { content: string; meta: Record<string, unknown> }) {
  const action = String(meta.action ?? '');
  const fileFull = String(meta.file ?? '');
  const fileName = fileFull.split(/[/\\]/).pop() ?? fileFull;
  const chars = Number(meta.chars ?? 0);

  if (action === 'saved') {
    return (
      <div className="flex items-center gap-2 flex-wrap">
        <AgentTagBadge tag="coder" color="#16a34a" />
        <FileCode size={12} className="text-emerald-600 shrink-0" />
        <span className="font-mono text-[12px] text-emerald-700 font-medium">{fileName}</span>
        <span className="text-[11px] text-muted-foreground">저장 완료</span>
        {chars > 0 && <span className="font-mono text-[10px] text-slate-400">{chars.toLocaleString()} chars</span>}
      </div>
    );
  }
  if (action === 'writing') {
    return (
      <div className="flex items-center gap-2 text-muted-foreground">
        <AgentTagBadge tag="coder" color="#16a34a" />
        <FileCode size={12} className="shrink-0" />
        <span className="font-mono text-[12px]">{fileName}</span>
        <span className="text-[11px]">작성 중…</span>
      </div>
    );
  }
  if (action === 'rejected' || action === 'no_code' || action === 'error') {
    const label = action === 'no_code' ? '코드 없음' : action === 'rejected' ? '저장 거부' : '오류';
    return (
      <div className="flex items-center gap-2 text-amber-700">
        <AgentTagBadge tag="coder" color="#d97706" />
        <AlertTriangle size={12} className="shrink-0" />
        <span className="font-mono text-[12px]">{fileName}</span>
        <span className="text-[11px]">{label}</span>
      </div>
    );
  }
  return <p className="text-[12px] text-foreground/90">{content}</p>;
}

const _EPOCH_PARSE_RE = /epoch\s*[\[:]?\s*(\d+)\s*[/\]]\s*(\d+)/i;
const _LOSS_PARSE_RE = /(?:train_?)?loss[:\s=]+([0-9]+\.?[0-9]*)/i;
const _ACC_PARSE_RE = /(?:train_?)?acc(?:uracy)?[:\s=]+([0-9]+\.?[0-9]*%?)/i;

function TrainingProgressCard({ content, meta }: { content: string; meta: Record<string, unknown> }) {
  const line = String(meta.epoch_line ?? content);
  const epochMatch = line.match(_EPOCH_PARSE_RE);
  const lossMatch = line.match(_LOSS_PARSE_RE);
  const accMatch = line.match(_ACC_PARSE_RE);
  const current = epochMatch ? Number(epochMatch[1]) : null;
  const total = epochMatch ? Number(epochMatch[2]) : null;
  const pct = current !== null && total ? Math.round((current / total) * 100) : null;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2 flex-wrap">
        <AgentTagBadge tag="train" color="#d97706" />
        {current !== null && total !== null && (
          <span className="font-mono text-[11px] text-amber-700 font-medium">Epoch {current}/{total}</span>
        )}
        {lossMatch && (
          <span className="font-mono text-[11px] text-slate-600 bg-slate-50 border border-slate-200 px-1.5 py-0.5 rounded">
            loss: {lossMatch[1]}
          </span>
        )}
        {accMatch && (
          <span className="font-mono text-[11px] text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded">
            acc: {accMatch[1]}
          </span>
        )}
      </div>
      {pct !== null && (
        <div className="h-1 w-full rounded-full bg-amber-100 overflow-hidden">
          <div
            className="h-full rounded-full bg-amber-400 transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
    </div>
  );
}

function PostProcessCard({ content }: { content: string }) {
  const body = content.replace(/^Post-process:\s*/i, '');
  return (
    <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
      <AgentTagBadge tag="postproc" color="#64748b" />
      <CheckSquare size={11} className="shrink-0 text-slate-400" />
      <span>{body}</span>
    </div>
  );
}

function DataSetupCard({ content }: { content: string }) {
  const isWarn = /warning|failed/i.test(content);
  const body = content.replace(/^\[DataSetup\]\s*/i, '');
  return (
    <div className={`flex items-center gap-2 text-[12px] ${isWarn ? 'text-amber-700' : 'text-sky-700'}`}>
      <AgentTagBadge tag="data" color={isWarn ? '#d97706' : '#0284c7'} />
      <Package size={12} className="shrink-0" />
      <span>{body}</span>
    </div>
  );
}

function CodeFixCard({ meta }: { meta: Record<string, unknown> }) {
  const attempt = Number(meta.code_fix_attempt ?? 1);
  const max = Number(meta.max_attempts ?? 2);
  return (
    <div className="inline-flex items-center gap-2 text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
      <Wrench size={11} className="shrink-0" />
      <span>코드 수정 시도 {attempt}/{max}</span>
      <span className="text-amber-400 text-[10px]">iteration 유지</span>
    </div>
  );
}

function CircuitBreakerCard({ meta }: { meta: Record<string, unknown> }) {
  const count = Number(meta.repair_count ?? 3);
  return (
    <div className="inline-flex items-center gap-2 text-[12px] text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1">
      <AlertTriangle size={12} className="shrink-0" />
      <span className="font-semibold">서킷 브레이커</span>
      <span className="text-red-400 text-[11px]">수정 {count}회 도달 — 중단</span>
    </div>
  );
}

function TaggedMessageContent({ event }: { event: LogEvent }) {
  const meta = (event.metadata ?? {}) as Record<string, unknown>;
  const tag = String(meta.agent_tag ?? '');
  const content = event.content ?? '';
  switch (tag) {
    case 'DirectExec':
      return String(meta.action) === 'running'
        ? <DirectExecRunningCard meta={meta} />
        : <DirectExecResultCard meta={meta} />;
    case 'DirectAnalyze':
      return <DirectAnalyzeCard meta={meta} />;
    case 'FileCoder':
      return <FileCoderTagCard content={content} meta={meta} />;
    case 'Training':
      return <TrainingProgressCard content={content} meta={meta} />;
    case 'PostProcess':
      return <PostProcessCard content={content} />;
    case 'DataSetup':
      return <DataSetupCard content={content} />;
    case 'CodeFix':
      return <CodeFixCard meta={meta} />;
    case 'CircuitBreaker':
      return <CircuitBreakerCard meta={meta} />;
    default:
      return null;
  }
}

// ─── MessageBubble ────────────────────────────────────────────────────────────

function MessageBubble({ event, color, onClick }: { event: LogEvent; color: AgentColor; onClick?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const content = event.content || '';
  const meta = (event.metadata ?? {}) as Record<string, unknown>;
  const agentTag = String(meta.agent_tag ?? '');

  // Tagged messages: compact, neutral container (no agent color tint)
  if (agentTag) {
    return (
      <div
        className="rounded-md px-2.5 py-1.5 cursor-pointer hover:bg-muted/60 transition-colors"
        onClick={onClick}
      >
        <TaggedMessageContent event={event} />
      </div>
    );
  }

  const isJson = content.trim().startsWith('{');
  const isLong = !isJson && content.length > 320;
  const displayed = isLong && !expanded ? `${content.slice(0, 320)}…` : content;
  const statusSnapshot = extractStatusSnapshot(event);

  return (
    <div
      className="rounded-lg px-3 py-2 text-[13px] leading-relaxed cursor-pointer transition-all hover:brightness-110"
      style={{ backgroundColor: color.bgColor, border: `1px solid ${color.borderColor}25` }}
      onClick={onClick}
    >
      <SmartMessageContent content={displayed} />
      {isLong && (
        <button
          onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
          className="mt-1 text-[11px] text-muted-foreground/50 hover:text-muted-foreground/80 transition-colors"
        >
          {expanded ? '접기' : '더 보기'}
        </button>
      )}
      {statusSnapshot && <MiniStatusRow snapshot={statusSnapshot} />}
    </div>
  );
}

function MiniStatusRow({ snapshot }: { snapshot: ReturnType<typeof extractStatusSnapshot> }) {
  if (!snapshot) return null;
  const items = [
    snapshot.executionSuccess !== undefined && {
      label: '실행',
      ok: snapshot.executionSuccess,
      text: snapshot.executionSuccess ? '성공' : '실패',
    },
    snapshot.needsRework !== undefined && {
      label: '재작업',
      ok: !snapshot.needsRework,
      text: snapshot.needsRework ? '필요' : '없음',
    },
    snapshot.readyForReport !== undefined && {
      label: '보고',
      ok: snapshot.readyForReport,
      text: snapshot.readyForReport ? '가능' : '보류',
    },
  ].filter(Boolean) as { label: string; ok: boolean; text: string }[];

  if (items.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {items.map((item) => (
        <span
          key={item.label}
          className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${
            item.ok
              ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
              : 'border-red-300 bg-red-50 text-red-600'
          }`}
        >
          {item.label} {item.text}
        </span>
      ))}
    </div>
  );
}

// ─── System dividers ──────────────────────────────────────────────────────────

function SystemDivider({ event, onEventClick }: { event: LogEvent; onEventClick?: (e: LogEvent) => void }) {
  const type = event.event_type;

  if (type === 'SYSTEM_START' || type === 'SYSTEM_END') {
    const isStart = type === 'SYSTEM_START';
    const failed = String(event.metadata?.status || '').toLowerCase() === 'failed';
    const color = isStart ? '#2563EB' : failed ? '#DC2626' : '#059669';
    const Icon = isStart ? Play : Square;
    const label = isStart ? 'SESSION START' : failed ? 'SESSION FAILED' : 'SESSION COMPLETE';
    const errorMsg = failed ? String(event.content || '').trim() : '';

    return (
      <div className="py-3 space-y-2">
        <div className="flex items-center gap-3">
          <div className="flex-1 h-px" style={{ background: `linear-gradient(to right, transparent, ${color}30)` }} />
          <div
            className="flex items-center gap-1.5 px-3 py-1 rounded-full border text-[10px] font-mono font-semibold"
            style={{ borderColor: `${color}30`, backgroundColor: `${color}08`, color }}
          >
            <Icon size={9} />
            {label}
          </div>
          <div className="flex-1 h-px" style={{ background: `linear-gradient(to left, transparent, ${color}30)` }} />
        </div>
        {failed && errorMsg && (
          <div className="mx-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2">
            <AlertTriangle size={13} className="text-red-500 shrink-0 mt-0.5" />
            <p className="text-[11px] font-mono text-red-700 leading-relaxed break-words">{errorMsg}</p>
          </div>
        )}
      </div>
    );
  }

  if (type === 'EXPERIMENT_START') {
    const iterLabel = extractIterationLabel(event.content || '');
    return (
      <div
        className="flex items-center gap-2 py-1.5 px-3 my-1 rounded-lg border border-amber-200 bg-amber-50 cursor-pointer hover:bg-amber-100/70 transition-colors"
        onClick={() => onEventClick?.(event)}
      >
        <FlaskConical size={11} className="text-amber-600 shrink-0" />
        <span className="text-[11px] font-mono text-amber-700">
          {iterLabel ? `${iterLabel} — 실험 실행 시작` : '실험 실행 시작'}
        </span>
        <span className="ml-auto text-[10px] font-mono text-muted-foreground/40">
          {formatTimestamp(event.timestamp)}
        </span>
      </div>
    );
  }

  if (type === 'EXPERIMENT_RESULT') {
    const success = event.metadata?.execution_success;
    const metric = event.metadata?.primary_metric_value;
    return (
      <div
        className="flex items-center gap-2 py-1.5 px-3 my-1 rounded-lg border border-emerald-200 bg-emerald-50 cursor-pointer hover:bg-emerald-100/70 transition-colors"
        onClick={() => onEventClick?.(event)}
      >
        <BarChart2 size={11} className="text-emerald-600 shrink-0" />
        <span className="text-[11px] font-mono text-emerald-700">
          {event.content || '실험 결과'}
        </span>
        {metric !== undefined && (
          <span className="text-[10px] font-mono text-emerald-700 border border-emerald-300 rounded px-1.5 py-0.5">
            {typeof metric === 'number' && metric < 1 ? `${(metric * 100).toFixed(2)}%` : String(metric)}
          </span>
        )}
        {success === false && (
          <span className="text-[10px] font-mono text-red-600 border border-red-300 rounded px-1.5 py-0.5">실패</span>
        )}
        <span className="ml-auto text-[10px] font-mono text-muted-foreground/40">
          {formatTimestamp(event.timestamp)}
        </span>
      </div>
    );
  }

  if (type === 'PHASE_COMPLETE') {
    const phaseName = String(event.metadata?.phase_name || event.content || '단계').trim();
    return (
      <div className="flex items-center gap-3 py-2">
        <div className="flex-1 h-px bg-emerald-200/60" />
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-emerald-200 bg-emerald-50">
          <CheckCircle2 size={9} className="text-emerald-600" />
          <span className="text-[10px] font-mono text-emerald-700">{phaseName}</span>
        </div>
        <div className="flex-1 h-px bg-emerald-200/60" />
      </div>
    );
  }

  if (type === 'WORKSPACE_GENERATION_START') {
    return (
      <div className="flex items-center gap-2 py-1 px-2 my-0.5">
        <div className="flex-1 h-px bg-border/30" />
        <span className="text-[10px] font-mono text-muted-foreground/40">워크스페이스 초기화</span>
        <div className="flex-1 h-px bg-border/30" />
      </div>
    );
  }

  return null;
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function AgentConversation({ events, onEventClick }: AgentConversationProps) {
  const timeline = useMemo(() => buildTimeline(events), [events]);

  if (timeline.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-xs font-mono text-muted-foreground/40">
        대기 중...
      </div>
    );
  }

  return (
    <div className="space-y-1 px-4 py-3">
      {timeline.map((item, i) => {
        if (item.kind === 'iteration') {
          return (
            <div key={`iter-${i}`} className="flex justify-center py-2">
              <div className="rounded-full border border-blue-200 bg-blue-50 px-3 py-0.5 text-[10px] font-mono uppercase tracking-[0.15em] text-blue-600">
                {item.label}
              </div>
            </div>
          );
        }
        if (item.kind === 'system') {
          return (
            <SystemDivider key={`sys-${i}`} event={item.event} onEventClick={onEventClick} />
          );
        }
        return (
          <AgentTurnCard key={`turn-${i}`} turn={item.turn} onEventClick={onEventClick} />
        );
      })}
    </div>
  );
}
