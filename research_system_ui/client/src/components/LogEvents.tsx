/**
 * 로그 이벤트별 UI 컴포넌트
 * Design: Mission Control 테마 — 다크 배경, 시안 액센트, 글로우 이펙트
 */

import { useState } from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { motion } from 'framer-motion';
import {
  Play, Square, Brain, MessageSquare, Wrench,
  FileText, Code, FlaskConical, BarChart3, HelpCircle, CheckCircle2,
  ChevronDown, ChevronRight, Copy, Check, ExternalLink,
  AlertTriangle, AlertOctagon, Lightbulb, Terminal,
} from 'lucide-react';
import type { LogEvent } from '@/lib/types';
import { getAgentColor, formatTimestamp } from '@/lib/constants';

// 애니메이션 변수
const slideIn = {
  initial: { opacity: 0, x: -20 },
  animate: { opacity: 1, x: 0 },
  transition: { duration: 0.15, ease: 'easeOut' as const },
};

// 이벤트 아이콘 매핑
function EventIcon({ type, className }: { type: string; className?: string }) {
  const iconProps = { size: 14, className };
  switch (type) {
    case 'SYSTEM_START': return <Play {...iconProps} />;
    case 'SYSTEM_END': return <Square {...iconProps} />;
    case 'AGENT_THINKING': return <Brain {...iconProps} />;
    case 'AGENT_MESSAGE': return <MessageSquare {...iconProps} />;
    case 'TOOL_CALL': return <Wrench {...iconProps} />;
    case 'TOOL_RESULT': return <CheckCircle2 {...iconProps} />;
    case 'FILE_CREATED': return <FileText {...iconProps} />;
    case 'CODE_BLOCK': return <Code {...iconProps} />;
    case 'EXPERIMENT_START': return <FlaskConical {...iconProps} />;
    case 'EXPERIMENT_RESULT': return <BarChart3 {...iconProps} />;
    case 'USER_QUESTION': return <HelpCircle {...iconProps} />;
    case 'PHASE_COMPLETE': return <CheckCircle2 {...iconProps} />;
    default: return <MessageSquare {...iconProps} />;
  }
}

// ─── SYSTEM_START / SYSTEM_END ───
export function SystemBanner({ event }: { event: LogEvent }) {
  const isStart = event.event_type === 'SYSTEM_START';
  const status = event.metadata?.status;
  const isFailed = status === 'failed';
  const isPaused = status === 'paused';

  let borderColor = 'border-blue-200';
  let bgColor = 'bg-blue-50';
  let textColor = 'text-blue-600';
  let glowClass = 'glow-cyan';

  if (!isStart) {
    if (isFailed) {
      borderColor = 'border-red-200';
      bgColor = 'bg-red-50';
      textColor = 'text-red-600';
      glowClass = '';
    } else if (isPaused) {
      borderColor = 'border-amber-200';
      bgColor = 'bg-amber-50';
      textColor = 'text-amber-600';
      glowClass = '';
    } else {
      borderColor = 'border-emerald-200';
      bgColor = 'bg-emerald-50';
      textColor = 'text-emerald-700';
      glowClass = '';
    }
  }

  return (
    <motion.div {...slideIn} className={`relative mx-4 my-3 rounded-lg border ${borderColor} ${bgColor} ${glowClass} overflow-hidden`}>
      <div className="flex items-center gap-3 px-4 py-3">
        <div className={`flex items-center justify-center w-7 h-7 rounded-md ${bgColor} ${textColor}`}>
          <EventIcon type={event.event_type} />
        </div>
        <div className="flex-1">
          <p className={`text-sm font-medium font-mono ${textColor}`}>
            {isStart ? 'SYSTEM INITIALIZED' : `SYSTEM ${status?.toUpperCase() || 'ENDED'}`}
          </p>
          <p className="text-xs text-muted-foreground mt-0.5">{event.content}</p>
        </div>
        <span className="text-[10px] font-mono text-muted-foreground">{formatTimestamp(event.timestamp)}</span>
      </div>
    </motion.div>
  );
}

// ─── AGENT_MESSAGE ───
export function AgentMessage({ event, onClick }: { event: LogEvent; onClick?: () => void }) {
  const color = getAgentColor(event.agent_name);

  return (
    <motion.div {...slideIn} className="px-4 py-2 group" onClick={onClick}>
      <div className="flex items-start gap-3">
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold font-mono shrink-0 mt-0.5"
          style={{ backgroundColor: color.bgColor, color: color.textColor, border: `1px solid ${color.borderColor}` }}
        >
          {(event.agent_name || 'S')[0]}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold font-mono" style={{ color: color.textColor }}>
              {event.agent_name}
            </span>
            <span className="text-[10px] font-mono text-muted-foreground">{formatTimestamp(event.timestamp)}</span>
          </div>
          <div
            className="rounded-lg px-3 py-2.5 text-sm leading-relaxed border"
            style={{ backgroundColor: color.bgColor, borderColor: color.borderColor }}
          >
            {(() => {
              const trimmed = event.content?.trim() ?? '';
              const looksLikeJson = (trimmed.startsWith('{') || trimmed.startsWith('[')) && trimmed.length > 2;
              if (looksLikeJson) {
                try {
                  const formatted = JSON.stringify(JSON.parse(trimmed), null, 2);
                  return (
                    <SyntaxHighlighter
                      language="json"
                      style={vscDarkPlus}
                      customStyle={{ margin: 0, padding: '0.5rem', borderRadius: '0.375rem', fontSize: '0.75rem', background: 'transparent' }}
                      wrapLongLines
                    >
                      {formatted}
                    </SyntaxHighlighter>
                  );
                } catch {
                  // not valid JSON — fall through to plain text
                }
              }
              return event.content;
            })()}
          </div>
        </div>
      </div>
    </motion.div>
  );
}

// ─── AGENT_THINKING ───
export function AgentThinking({ event }: { event: LogEvent }) {
  const [isOpen, setIsOpen] = useState(false);
  const color = getAgentColor(event.agent_name);

  return (
    <motion.div {...slideIn} className="px-4 py-1.5">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors w-full text-left group"
      >
        <div className="w-8 flex justify-center">
          {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </div>
        <Brain size={12} className="text-muted-foreground/60" />
        <span className="font-mono" style={{ color: color.textColor + '99' }}>{event.agent_name}</span>
        <span className="text-muted-foreground/60">의 사고 과정</span>
        <span className="text-[10px] font-mono ml-auto">{formatTimestamp(event.timestamp)}</span>
      </button>
      {isOpen && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          transition={{ duration: 0.2 }}
          className="ml-11 mt-1.5 rounded-lg bg-muted/30 border border-border/50 px-3 py-2.5 text-xs text-muted-foreground leading-relaxed italic"
        >
          {event.content}
        </motion.div>
      )}
    </motion.div>
  );
}

// ─── TOOL_CALL ───
export function ToolCall({ event, onClick }: { event: LogEvent; onClick?: () => void }) {
  const toolName = String(event.metadata?.tool_name || 'Tool');
  const toolInput = event.metadata?.tool_input as Record<string, unknown> | undefined;

  return (
    <motion.div {...slideIn} className="px-4 py-1.5" onClick={onClick}>
      <div className="rounded-lg border border-border/40 bg-muted/20 px-3 py-2 cursor-pointer hover:border-border/60 transition-colors">
        <div className="flex items-center gap-2 mb-1.5">
          <Wrench size={11} className="text-muted-foreground/60" />
          <span className="text-[11px] font-semibold font-mono text-muted-foreground/80">{toolName}</span>
          <span className="text-[10px] font-mono text-muted-foreground/40 ml-auto">{formatTimestamp(event.timestamp)}</span>
        </div>
        {toolInput && (
          <div className="space-y-0.5">
            {Object.entries(toolInput).map(([k, v]) => (
              <div key={k} className="flex gap-2 text-[11px] font-mono">
                <span className="text-muted-foreground/40">{k}:</span>
                <span className="text-muted-foreground/70 break-all">
                  {String(v).length > 120 ? `${String(v).slice(0, 120)}…` : String(v)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}

// ─── TOOL_RESULT ───
export function ToolResult({ event, onClick }: { event: LogEvent; onClick?: () => void }) {
  const success = event.metadata?.success !== false;

  return (
    <motion.div {...slideIn} className="px-4 py-1.5" onClick={onClick}>
      <div className={`rounded-lg border px-3 py-2 cursor-pointer transition-colors ${
        success ? 'border-emerald-500/25 bg-emerald-500/5 hover:border-emerald-500/40' : 'border-red-500/25 bg-red-500/5 hover:border-red-500/40'
      }`}>
        <div className="flex items-center gap-2 mb-1">
          <span className={`text-[11px] font-semibold font-mono ${success ? 'text-emerald-400' : 'text-red-400'}`}>
            {success ? '✓ 완료' : '✗ 실패'}
          </span>
          <span className="text-[10px] font-mono text-muted-foreground/40 ml-auto">{formatTimestamp(event.timestamp)}</span>
        </div>
        {event.content && (
          <p className="text-[11px] text-muted-foreground/70 leading-relaxed line-clamp-3">{event.content}</p>
        )}
      </div>
    </motion.div>
  );
}

// ─── FILE_CREATED ───
export function FileCreated({ event, onClick }: { event: LogEvent; onClick?: () => void }) {
  const color = getAgentColor(event.agent_name);

  return (
    <motion.div {...slideIn} className="px-4 py-1.5">
      <div className="flex items-center gap-3">
        <div className="w-8 flex justify-center">
          <FileText size={14} className="text-emerald-400/70" />
        </div>
        <button
          onClick={onClick}
          className="flex items-center gap-2 text-xs font-mono text-emerald-400/80 hover:text-emerald-400 transition-colors group"
        >
          <span style={{ color: color.textColor + '80' }}>{event.agent_name}</span>
          <span className="text-muted-foreground/50">→</span>
          <span className="underline underline-offset-2 decoration-emerald-400/30 group-hover:decoration-emerald-400/60">
            {event.metadata?.file_path}
          </span>
          <ExternalLink size={10} className="opacity-0 group-hover:opacity-100 transition-opacity" />
        </button>
        <span className="text-[10px] font-mono text-muted-foreground ml-auto">{formatTimestamp(event.timestamp)}</span>
      </div>
    </motion.div>
  );
}

// ─── CODE_BLOCK ───
export function CodeBlock({ event, onClick }: { event: LogEvent; onClick?: () => void }) {
  const [copied, setCopied] = useState(false);
  const color = getAgentColor(event.agent_name);
  const language = event.metadata?.language || 'python';

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(event.content || '');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <motion.div {...slideIn} className="px-4 py-2" onClick={onClick}>
      <div className="flex items-start gap-3">
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
          style={{ backgroundColor: color.bgColor, color: color.textColor, border: `1px solid ${color.borderColor}` }}
        >
          <Code size={14} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-mono" style={{ color: color.textColor }}>{event.agent_name}</span>
            <span className="text-[10px] font-mono text-muted-foreground">{formatTimestamp(event.timestamp)}</span>
          </div>
          <div className="rounded-lg border border-border/50 overflow-hidden bg-[#1e1e1e]">
            <div className="flex items-center justify-between px-3 py-1.5 bg-[#252526] border-b border-border/30">
              <span className="text-[10px] font-mono text-muted-foreground uppercase">{language}</span>
              <button
                onClick={handleCopy}
                className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
              >
                {copied ? <Check size={10} className="text-emerald-400" /> : <Copy size={10} />}
                {copied ? '복사됨' : '복사'}
              </button>
            </div>
            <SyntaxHighlighter
              language={language}
              style={vscDarkPlus}
              customStyle={{
                margin: 0,
                padding: '12px',
                fontSize: '11px',
                lineHeight: '1.5',
                background: 'transparent',
                maxHeight: '300px',
              }}
              showLineNumbers
              lineNumberStyle={{ color: '#555', fontSize: '10px' }}
            >
              {event.content || ''}
            </SyntaxHighlighter>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

// ─── EXPERIMENT_START ───
export function ExperimentStart({ event }: { event: LogEvent }) {
  return (
    <motion.div {...slideIn} className="px-4 py-2">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-amber-500/10 border border-amber-500/30 shrink-0">
          <FlaskConical size={14} className="text-amber-400" />
        </div>
        <div className="flex-1 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2.5">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-amber-400 font-mono">EXPERIMENT RUNNING</span>
              <span className="text-[10px] text-amber-300/70 font-mono">{event.metadata?.experiment_id}</span>
            </div>
            <span className="text-[10px] font-mono text-muted-foreground">{formatTimestamp(event.timestamp)}</span>
          </div>
          <div className="h-1.5 bg-amber-500/10 rounded-full overflow-hidden">
            <div className="h-full bg-gradient-to-r from-amber-500 to-amber-400 rounded-full animate-pulse" style={{ width: '60%' }} />
          </div>
        </div>
      </div>
    </motion.div>
  );
}

// ─── EXPERIMENT_RESULT ───
export function ExperimentResult({ event, onClick }: { event: LogEvent; onClick?: () => void }) {
  const metrics = event.metadata?.metrics;
  const color = getAgentColor(event.agent_name);

  return (
    <motion.div {...slideIn} className="px-4 py-2" onClick={onClick}>
      <div className="flex items-start gap-3">
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
          style={{ backgroundColor: color.bgColor, color: color.textColor, border: `1px solid ${color.borderColor}` }}
        >
          <BarChart3 size={14} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-mono" style={{ color: color.textColor }}>{event.agent_name}</span>
            <span className="text-[10px] font-mono text-muted-foreground">{formatTimestamp(event.timestamp)}</span>
          </div>
          <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2.5 glow-emerald">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-semibold text-emerald-400 font-mono">EXPERIMENT RESULT</span>
            </div>
            {event.content && <p className="text-xs text-muted-foreground mb-2">{event.content}</p>}
            {metrics && (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-2">
                {Object.entries(metrics).map(([key, value]) => (
                  <div key={key} className="bg-background/40 rounded px-2 py-1.5">
                    <p className="text-[10px] text-muted-foreground font-mono uppercase">{key.replace(/_/g, ' ')}</p>
                    <p className="text-sm font-semibold text-emerald-300 font-mono">
                      {typeof value === 'number' ? (value < 1 && value > 0 ? `${(value * 100).toFixed(2)}%` : value.toFixed(2)) : String(value)}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
}

// ─── USER_QUESTION ───
export function UserQuestion({ event }: { event: LogEvent }) {
  return (
    <motion.div {...slideIn} className="px-4 py-2">
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-amber-500/15 border border-amber-500/30 shrink-0 mt-0.5">
          <HelpCircle size={14} className="text-amber-400" />
        </div>
        <div className="flex-1 rounded-lg border border-amber-500/30 bg-amber-500/8 px-3 py-2.5 glow-amber">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-xs font-semibold text-amber-400 font-mono">USER INPUT REQUIRED</span>
            <span className="text-[10px] font-mono text-muted-foreground">{formatTimestamp(event.timestamp)}</span>
          </div>
          <p className="text-sm text-amber-200/90 leading-relaxed">{event.content}</p>
        </div>
      </div>
    </motion.div>
  );
}

// ─── PHASE_COMPLETE ───
export function PhaseComplete({ event }: { event: LogEvent }) {
  const phaseNum = event.metadata?.phase ?? event.metadata?.phase_number;
  const phaseName = event.metadata?.phase_name;

  return (
    <motion.div {...slideIn} className="px-4 py-3">
      <div className="flex items-center gap-3">
        <div className="flex-1 h-px bg-gradient-to-r from-transparent via-emerald-500/30 to-transparent" />
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/5">
          <CheckCircle2 size={12} className="text-emerald-400" />
          <span className="text-[11px] font-semibold text-emerald-400 font-mono">
            Phase {phaseNum}: {phaseName || event.content}
          </span>
          <span className="text-[10px] text-emerald-400/60">완료</span>
        </div>
        <div className="flex-1 h-px bg-gradient-to-r from-transparent via-emerald-500/30 to-transparent" />
      </div>
    </motion.div>
  );
}

// ─── FILE_GENERATED ───
function FileGenerated({ event }: { event: LogEvent }) {
  const filePath = (event.metadata?.file_path as string) || event.content || '';
  const stage = event.metadata?.stage as number | undefined;
  return (
    <motion.div {...slideIn} className="px-4 py-1">
      <div className="flex items-center gap-2 text-[11px] font-mono">
        <CheckCircle2 size={11} className="text-emerald-400 shrink-0" />
        <span className="text-emerald-400/80">생성됨</span>
        <span className="text-muted-foreground/80">{filePath}</span>
        {stage !== undefined && (
          <span className="px-1 rounded text-[9px] bg-emerald-500/10 text-emerald-400/60 border border-emerald-500/15">
            S{stage}
          </span>
        )}
        <span className="ml-auto text-[10px] text-muted-foreground shrink-0">{formatTimestamp(event.timestamp)}</span>
      </div>
    </motion.div>
  );
}

// ─── FILE_SYNTAX_ERROR / FILE_IMPORT_ERROR ───
function FileError({ event }: { event: LogEvent }) {
  const isImport = event.event_type === 'FILE_IMPORT_ERROR';
  const filePath = (event.metadata?.file_path as string) || '';
  const errorText = (event.metadata?.error as string) || event.content || '';
  return (
    <motion.div {...slideIn} className="px-4 py-1">
      <div className="flex items-start gap-2 rounded border border-red-500/20 bg-red-500/5 px-2.5 py-1.5 text-[11px] font-mono">
        <AlertTriangle size={11} className="text-red-400 shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <span className="text-red-400 font-semibold">{isImport ? 'ImportError' : 'SyntaxError'} </span>
          <span className="text-muted-foreground/70">{filePath}</span>
          {errorText && (
            <p className="text-muted-foreground/50 mt-0.5 truncate">{errorText.slice(0, 120)}</p>
          )}
        </div>
        <span className="text-[10px] text-muted-foreground shrink-0">{formatTimestamp(event.timestamp)}</span>
      </div>
    </motion.div>
  );
}

// ─── FILE_FIXED ───
function FileFixed({ event }: { event: LogEvent }) {
  const filePath = (event.metadata?.file_path as string) || '';
  const attempt = event.metadata?.attempt as number | undefined;
  return (
    <motion.div {...slideIn} className="px-4 py-1">
      <div className="flex items-center gap-2 text-[11px] font-mono">
        <CheckCircle2 size={11} className="text-sky-400 shrink-0" />
        <span className="text-sky-400">수정 완료</span>
        <span className="text-muted-foreground/70">{filePath}</span>
        {attempt !== undefined && (
          <span className="text-muted-foreground/40">({attempt}회 시도)</span>
        )}
        <span className="ml-auto text-[10px] text-muted-foreground shrink-0">{formatTimestamp(event.timestamp)}</span>
      </div>
    </motion.div>
  );
}

// ─── SMOKE_TEST_DONE ───
function SmokeTestDone({ event }: { event: LogEvent }) {
  const passed = event.metadata?.passed as boolean;
  return (
    <motion.div {...slideIn} className="px-4 py-1.5">
      <div className={`flex items-center gap-2 rounded-md border px-3 py-1.5 text-[11px] font-mono ${
        passed
          ? 'border-emerald-500/25 bg-emerald-500/5 text-emerald-400'
          : 'border-red-500/25 bg-red-500/5 text-red-400'
      }`}>
        {passed
          ? <CheckCircle2 size={11} className="shrink-0" />
          : <AlertTriangle size={11} className="shrink-0" />
        }
        <span className="font-semibold">Smoke Test {passed ? 'PASSED' : 'FAILED'}</span>
        {event.content && <span className="text-muted-foreground/70 ml-1">{event.content}</span>}
        <span className="ml-auto text-[10px] text-muted-foreground">{formatTimestamp(event.timestamp)}</span>
      </div>
    </motion.div>
  );
}

// ─── SECTION_DRAFT_DONE ───
function SectionDone({ event }: { event: LogEvent }) {
  return (
    <motion.div {...slideIn} className="px-4 py-1.5">
      <div className="flex items-center gap-2 text-[11px] font-mono text-muted-foreground">
        <FileText size={11} className="text-blue-400" />
        <span className="text-blue-500">섹션 초안 완료</span>
        <span className="text-muted-foreground/70">{event.content}</span>
        <span className="ml-auto text-[10px]">{formatTimestamp(event.timestamp)}</span>
      </div>
    </motion.div>
  );
}

// ─── PREFLIGHT_QUESTION (로그에 표시되는 카드 — 실제 응답은 PreflightFlow에서) ───
function PreflightCard({ event }: { event: LogEvent }) {
  return (
    <motion.div {...slideIn} className="px-4 py-2">
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2.5">
        <div className="flex items-center gap-2 mb-1.5">
          <HelpCircle size={13} className="text-amber-400" />
          <span className="text-xs font-semibold text-amber-400 font-mono">실행 전 확인</span>
          <span className="text-[10px] font-mono text-muted-foreground ml-auto">{formatTimestamp(event.timestamp)}</span>
        </div>
        <p className="text-sm text-foreground leading-relaxed">{event.content}</p>
        {!!event.metadata?.default && (
          <p className="text-[11px] text-muted-foreground mt-1.5 font-mono">기본값: {String(event.metadata.default)}</p>
        )}
      </div>
    </motion.div>
  );
}

// ─── PREFLIGHT_ANSWERED ───
function PreflightAnswered({ event }: { event: LogEvent }) {
  return (
    <motion.div {...slideIn} className="px-4 py-1.5">
      <div className="flex items-center gap-2 text-[11px] font-mono text-muted-foreground">
        <CheckCircle2 size={11} className="text-emerald-400" />
        <span>실행 전 확인 완료</span>
        {event.content && <span className="text-muted-foreground/60">— {event.content}</span>}
        <span className="ml-auto text-[10px]">{formatTimestamp(event.timestamp)}</span>
      </div>
    </motion.div>
  );
}

// ─── exec_stdout ───
function StdoutLine({ event }: { event: LogEvent }) {
  return (
    <div className="px-4 py-0 font-mono text-[11px] leading-relaxed" style={{ color: 'oklch(0.72 0.12 145)' }}>
      <span className="text-zinc-600 select-none mr-2 text-[10px]">▶</span>
      {event.content}
    </div>
  );
}

// ─── token_budget_warning ───
function TokenBudgetWarning({ event }: { event: LogEvent }) {
  const ratio = (event.metadata?.ratio as number) || 0;
  const percent = Math.round(ratio * 100);
  return (
    <motion.div {...slideIn} className="px-4 py-1.5">
      <div className="flex items-center gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs">
        <AlertTriangle size={11} className="text-amber-500 shrink-0" />
        <span className="text-amber-600 font-mono font-semibold">토큰 예산 {percent}% 사용</span>
        <span className="text-muted-foreground">{event.content}</span>
        <span className="ml-auto text-[10px] font-mono text-muted-foreground">{formatTimestamp(event.timestamp)}</span>
      </div>
    </motion.div>
  );
}

// ─── failure_escalation ───
function FailureAlert({ event }: { event: LogEvent }) {
  const kind = event.metadata?.kind as string;
  return (
    <motion.div {...slideIn} className="px-4 py-2">
      <div className="rounded-lg border border-red-500/40 bg-red-500/5 px-3 py-2.5">
        <div className="flex items-center gap-2 mb-1">
          <AlertOctagon size={13} className="text-red-500" />
          <span className="text-xs font-semibold text-red-500 font-mono">
            반복 실패 감지 {kind ? `(${kind})` : ''}
          </span>
          <span className="text-[10px] font-mono text-muted-foreground ml-auto">{formatTimestamp(event.timestamp)}</span>
        </div>
        <p className="text-xs text-red-400/80">{event.content}</p>
        {!!event.metadata?.pattern_summary && (
          <p className="text-[11px] text-muted-foreground mt-1 font-mono">{String(event.metadata.pattern_summary)}</p>
        )}
      </div>
    </motion.div>
  );
}

// ─── extension_proposals ───
function ProposalTrigger({ event }: { event: LogEvent }) {
  const proposals = (event.metadata?.proposals as string[]) || [];
  return (
    <motion.div {...slideIn} className="px-4 py-2">
      <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 px-3 py-2.5">
        <div className="flex items-center gap-2 mb-2">
          <Lightbulb size={13} className="text-blue-400" />
          <span className="text-xs font-semibold text-blue-500 font-mono">
            추가 실험 제안 ({proposals.length}개)
          </span>
          <Terminal size={11} className="text-muted-foreground/40 ml-auto" />
        </div>
        {proposals.slice(0, 3).map((p, i) => (
          <p key={i} className="text-xs text-muted-foreground py-0.5">• {p}</p>
        ))}
      </div>
    </motion.div>
  );
}

// ─── 레지스트리 기반 이벤트 렌더러 ───

type EventRenderer = React.ComponentType<{ event: LogEvent; onClick?: () => void }>;

const EVENT_RENDERERS: Record<string, EventRenderer | null> = {
  SYSTEM_START:            ({ event }) => <SystemBanner event={event} />,
  SYSTEM_END:              ({ event }) => <SystemBanner event={event} />,
  AGENT_MESSAGE:           AgentMessage,
  AGENT_THINKING:          AgentThinking,
  TOOL_CALL:               ToolCall,
  TOOL_RESULT:             ToolResult,
  FILE_CREATED:            FileCreated,
  FILE_GENERATED:          ({ event }) => <FileGenerated event={event} />,
  FILE_SYNTAX_ERROR:       ({ event }) => <FileError event={event} />,
  FILE_IMPORT_ERROR:       ({ event }) => <FileError event={event} />,
  FILE_FIXED:              ({ event }) => <FileFixed event={event} />,
  FILE_GENERATION_FAILED:  ({ event }) => <FileError event={event} />,
  SMOKE_TEST_DONE:         ({ event }) => <SmokeTestDone event={event} />,
  SMOKE_TEST_START:        null,
  SMOKE_TEST_SKIPPED:      null,
  FILE_GENERATION_START:   null,
  CODE_BLOCK:              CodeBlock,
  EXPERIMENT_START:        ({ event }) => <ExperimentStart event={event} />,
  EXPERIMENT_RESULT:       ExperimentResult,
  USER_QUESTION:           ({ event }) => <UserQuestion event={event} />,
  PHASE_COMPLETE:          ({ event }) => <PhaseComplete event={event} />,
  SECTION_DRAFT_DONE:      ({ event }) => <SectionDone event={event} />,
  PREFLIGHT_QUESTION:      ({ event }) => <PreflightCard event={event} />,
  PREFLIGHT_ANSWERED:      ({ event }) => <PreflightAnswered event={event} />,
  exec_stdout:             ({ event }) => <StdoutLine event={event} />,
  token_budget_warning:    ({ event }) => <TokenBudgetWarning event={event} />,
  failure_escalation:      ({ event }) => <FailureAlert event={event} />,
  extension_proposals:     ({ event }) => <ProposalTrigger event={event} />,
  // 이벤트 목록에 표시하지 않음 — 전용 UI에서 처리
  PHASE_START:             null,
  WORKSPACE_GENERATION_START: null,
  PLAN_AWAITING_APPROVAL:  null,
  USER_GUIDANCE_NEEDED:    null,
  USER_GUIDANCE_RECEIVED:  null,
  token_budget_snapshot:   null,
};

export function LogEventRenderer({
  event,
  onEventClick,
}: {
  event: LogEvent;
  onEventClick?: (event: LogEvent) => void;
  searchQuery?: string;
}) {
  const handleClick = onEventClick ? () => onEventClick(event) : undefined;
  const Renderer = EVENT_RENDERERS[event.event_type];

  // null → 명시적 숨김
  if (Renderer === null) return null;

  // undefined → 미등록 이벤트 기본 렌더러
  if (Renderer === undefined) {
    return (
      <div className="px-4 py-1.5 text-xs text-muted-foreground font-mono">
        [{event.event_type}] {event.content}
      </div>
    );
  }

  return <Renderer event={event} onClick={handleClick} />;
}
