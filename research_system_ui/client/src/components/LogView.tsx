import { useEffect, useRef, useMemo, useState, useCallback } from 'react';
import { ArrowDown, CheckCircle2, Circle, Loader2, Pause, Play, Radio, RotateCcw, SkipForward, XCircle } from 'lucide-react';
import type { LogEvent, FilterState, Session, SessionStatus } from '@/lib/types';
import AgentConversation from './AgentConversation';
import { Spinner } from '@/components/ui/spinner';
import { ARCHITECTURE_COLORS, getStatusColor, getStatusLabel } from '@/lib/constants';
import {
  analyzeLogEvents,
  getArchitectureProfile,
  getArchitectureSpotlight,
  getSessionSignature,
} from '@/lib/architecture';

interface LogViewProps {
  session: Session;
  events: LogEvent[];
  filters: FilterState;
  onEventClick: (event: LogEvent) => void;
  searchQuery: string;
}

// ─── Phase Stepper ────────────────────────────────────────────────────────────

type PhaseStatus = 'pending' | 'running' | 'done' | 'failed';

interface PipelinePhase {
  id: string;
  label: string;
  status: PhaseStatus;
}

// V4 파이프라인 Phase 정의 (Phase 0–4)
const V4_PHASE_LABELS = ['Workspace', 'Planning', 'Coding', 'Execution', 'Writing'];

function detectPhases(events: LogEvent[], sessionStatus: SessionStatus): PipelinePhase[] {
  const phases: PipelinePhase[] = V4_PHASE_LABELS.map((label, i) => ({
    id: `phase-${i}`,
    label,
    status: 'pending' as PhaseStatus,
  }));

  const setStatus = (idx: number, s: PhaseStatus) => {
    if (idx >= 0 && idx < phases.length && phases[idx].status !== 'done' && phases[idx].status !== 'failed') {
      phases[idx] = { ...phases[idx], status: s };
    }
  };

  // metadata.phase 기반 우선 검출 (V4 파이프라인)
  let hasMetadataPhase = false;
  for (const event of events) {
    const phaseNum = event.metadata?.phase as number | undefined;
    if (phaseNum != null) {
      if (event.event_type === 'PHASE_START') { setStatus(phaseNum, 'running'); hasMetadataPhase = true; }
      if (event.event_type === 'PHASE_COMPLETE') { setStatus(phaseNum, 'done'); hasMetadataPhase = true; }
    }
  }

  // 체크포인트 재개 감지
  const resumeEvent = events.find(e => e.content?.includes('Resuming from checkpoint'));
  if (resumeEvent) {
    const resumePhase = resumeEvent.metadata?.checkpoint_phase as number | undefined;
    if (resumePhase != null) {
      for (let i = 0; i < resumePhase; i++) setStatus(i, 'done');
    }
  }

  // 폴백: 이전 버전 content 기반 감지 (V3 세션 호환)
  if (!hasMetadataPhase) {
    for (const event of events) {
      const c = (event.content ?? '').toLowerCase();
      if (c.includes('planner') || c.includes('experiment design')) setStatus(1, 'running');
      if (c.includes('manifest finalized') || c.includes('coder context file written')) setStatus(1, 'done');
      if (c.includes('filecoder') || c.includes('writing src/')) setStatus(2, 'running');
      if (c.includes('phase 1d complete') || c.includes('proceeding to phase 2')) setStatus(2, 'done');
      if (event.event_type === 'EXPERIMENT_START') { setStatus(2, 'done'); setStatus(3, 'running'); }
      if (event.event_type === 'EXPERIMENT_RESULT') setStatus(3, 'done');
      if (c.includes('research paper writer') || c.includes('writing report')) setStatus(4, 'running');
    }
  }

  // 터미널 상태 처리
  if (sessionStatus === 'completed') phases.forEach((p, i) => { if (p.status === 'running') phases[i] = { ...p, status: 'done' }; });
  if (sessionStatus === 'failed') phases.forEach((p, i) => { if (p.status === 'running') phases[i] = { ...p, status: 'failed' }; });

  return phases;
}

function PhaseStepperRow({ phases, isResumed, resumedFromPhase }: {
  phases: PipelinePhase[];
  isResumed?: boolean;
  resumedFromPhase?: number;
}) {
  return (
    <div className="flex items-center gap-0 px-4 py-2 overflow-x-auto">
      {phases.map((phase, i) => (
        <div key={phase.id} className="flex items-center">
          <div className="flex items-center gap-1.5 shrink-0">
            {phase.status === 'done' && <CheckCircle2 size={11} className="text-emerald-500" />}
            {phase.status === 'running' && <Loader2 size={11} className="text-blue-500 animate-spin" />}
            {phase.status === 'failed' && <XCircle size={11} className="text-red-500" />}
            {phase.status === 'pending' && <Circle size={11} className="text-muted-foreground/30" />}
            <span
              className={`text-[10px] font-mono ${
                phase.status === 'done' ? 'text-emerald-600' :
                phase.status === 'running' ? 'text-blue-600 font-semibold' :
                phase.status === 'failed' ? 'text-red-600' :
                'text-muted-foreground/40'
              }`}
            >
              {phase.label}
            </span>
            {isResumed && resumedFromPhase === i && (
              <span title={`Phase ${i}에서 재개됨`}>
                <RotateCcw size={9} className="text-amber-400 ml-0.5" />
              </span>
            )}
          </div>
          {i < phases.length - 1 && (
            <div className={`mx-2 h-px w-5 shrink-0 ${
              phases[i + 1].status !== 'pending' ? 'bg-emerald-300' : 'bg-border/40'
            }`} />
          )}
        </div>
      ))}
    </div>
  );
}

// ─── WaitingIndicator ─────────────────────────────────────────────────────────

function WaitingIndicator({ compact = false }: { compact?: boolean }) {
  if (compact) {
    return (
      <div className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-[10px] font-mono text-blue-600">
        <Spinner className="size-3 text-blue-500" />
        <span>다음 응답 대기 중</span>
        <span className="flex items-center gap-1">
          <span className="h-1 w-1 rounded-full bg-blue-400 animate-[wait-dot_1.2s_ease-in-out_infinite]" />
          <span className="h-1 w-1 rounded-full bg-blue-400 animate-[wait-dot_1.2s_ease-in-out_0.2s_infinite]" />
          <span className="h-1 w-1 rounded-full bg-blue-400 animate-[wait-dot_1.2s_ease-in-out_0.4s_infinite]" />
        </span>
      </div>
    );
  }

  return (
    <div className="mx-auto mb-4 w-full max-w-3xl px-4">
      <div className="relative overflow-hidden rounded-2xl border border-blue-200 bg-white px-4 py-3 shadow-sm">
        <div className="relative flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full border border-blue-200 bg-blue-50">
            <Spinner className="size-4 text-blue-500" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
              <span>다음 응답 대기 중</span>
              <span className="flex items-center gap-1">
                <span className="h-1.5 w-1.5 rounded-full bg-blue-400 animate-[wait-dot_1.2s_ease-in-out_infinite]" />
                <span className="h-1.5 w-1.5 rounded-full bg-blue-400 animate-[wait-dot_1.2s_ease-in-out_0.2s_infinite]" />
                <span className="h-1.5 w-1.5 rounded-full bg-blue-400 animate-[wait-dot_1.2s_ease-in-out_0.4s_infinite]" />
              </span>
            </div>
            <p className="mt-1 text-xs font-mono text-muted-foreground">
              에이전트가 다음 메시지 또는 실행 결과를 준비하는 중입니다.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function ArchitectureIdentityPanel({ session, events }: { session: Session; events: LogEvent[] }) {
  const archColor = ARCHITECTURE_COLORS[session.architecture] || ARCHITECTURE_COLORS.CrewAI;
  const profile = getArchitectureProfile(session.architecture);
  const signature = getSessionSignature(session, events);
  const spotlight = getArchitectureSpotlight(session, events);
  const analytics = analyzeLogEvents(events);

  return (
    <div className="border-b border-border/40 bg-card/35 px-4 py-3">
      <div className="rounded-2xl border border-border/40 bg-background/40 p-4">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className="rounded-full px-2 py-0.5 text-[10px] font-bold font-mono uppercase tracking-wider"
                style={{ color: archColor.text, backgroundColor: archColor.bg, border: `1px solid ${archColor.border}` }}
              >
                {profile.label}
              </span>
              <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
                {profile.executionModel}
              </span>
            </div>
            <h3 className="mt-3 text-base font-semibold text-foreground">{profile.tagline}</h3>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">{profile.summary}</p>

            <div className="mt-3 flex flex-wrap gap-1.5">
              {signature.map((item) => (
                <span
                  key={item}
                  className="rounded-full px-2 py-1 text-[10px] font-mono"
                  style={{ color: archColor.text, backgroundColor: archColor.bg }}
                >
                  {item}
                </span>
              ))}
              {profile.strengths.map((item) => (
                <span key={item} className="rounded-full bg-muted/50 px-2 py-1 text-[10px] font-mono text-muted-foreground">
                  {item}
                </span>
              ))}
            </div>
          </div>

          <div className="grid min-w-0 grid-cols-1 gap-2 md:grid-cols-3 xl:min-w-[440px]">
            {spotlight.map((item) => (
              <div key={item.label} className="rounded-xl border border-border/30 bg-card/70 px-3 py-2.5">
                <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">{item.label}</p>
                <p className="mt-1 text-sm font-semibold text-foreground">{item.value}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4">
          <div className="rounded-xl border border-border/20 bg-card/60 px-3 py-2">
            <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Turns</p>
            <p className="mt-1 text-sm font-semibold font-mono text-foreground">{analytics.agentTurns}</p>
          </div>
          <div className="rounded-xl border border-border/20 bg-card/60 px-3 py-2">
            <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Tools</p>
            <p className="mt-1 text-sm font-semibold font-mono text-foreground">{analytics.toolCalls}</p>
          </div>
          <div className="rounded-xl border border-border/20 bg-card/60 px-3 py-2">
            <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Runs</p>
            <p className="mt-1 text-sm font-semibold font-mono text-foreground">
              {analytics.experimentResults || analytics.experimentStarts}
            </p>
          </div>
          <div className="rounded-xl border border-border/20 bg-card/60 px-3 py-2">
            <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Roles</p>
            <p className="mt-1 text-sm font-semibold font-mono text-foreground">
              {analytics.uniqueAgents || session.agents.length}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function LogView({ session, events, filters, onEventClick, searchQuery }: LogViewProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const isAutoScroll = useRef(true);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamIndex, setStreamIndex] = useState(events.length);
  const streamTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const filteredEvents = useMemo(() => {
    const visibleEvents = events.slice(0, streamIndex);
    return visibleEvents.filter((event) => {
      if (filters.agents.length > 0 && event.agent_name && !filters.agents.includes(event.agent_name)) {
        return false;
      }
      if (filters.eventTypes.length > 0 && !filters.eventTypes.includes(event.event_type)) {
        return false;
      }
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        const contentMatch = event.content?.toLowerCase().includes(query);
        const agentMatch = event.agent_name?.toLowerCase().includes(query);
        const toolMatch = event.metadata?.tool_name?.toLowerCase().includes(query);
        if (!contentMatch && !agentMatch && !toolMatch) {
          return false;
        }
      }
      return true;
    });
  }, [events, filters.agents, filters.eventTypes, searchQuery, streamIndex]);

  useEffect(() => {
    if (isAutoScroll.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filteredEvents.length]);

  const startStreaming = useCallback(() => {
    setStreamIndex(0);
    setIsStreaming(true);
  }, []);

  const stopStreaming = useCallback(() => {
    setIsStreaming(false);
    if (streamTimerRef.current) {
      clearTimeout(streamTimerRef.current);
      streamTimerRef.current = null;
    }
  }, []);

  const skipToEnd = useCallback(() => {
    stopStreaming();
    setStreamIndex(events.length);
  }, [events.length, stopStreaming]);

  useEffect(() => {
    if (isStreaming && streamIndex < events.length) {
      const delay = Math.random() * 600 + 200;
      streamTimerRef.current = setTimeout(() => {
        setStreamIndex((prev) => prev + 1);
      }, delay);
    } else if (streamIndex >= events.length) {
      setIsStreaming(false);
    }

    return () => {
      if (streamTimerRef.current) {
        clearTimeout(streamTimerRef.current);
      }
    };
  }, [isStreaming, streamIndex, events.length]);

  useEffect(() => {
    setStreamIndex(events.length);
    setIsStreaming(false);
  }, [session.run_id, events.length]);

  const handleScroll = () => {
    if (!scrollRef.current) {
      return;
    }
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    isAutoScroll.current = scrollHeight - scrollTop - clientHeight < 50;
  };

  const scrollToBottom = () => {
    if (!scrollRef.current) {
      return;
    }
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    isAutoScroll.current = true;
  };

  const archColor = ARCHITECTURE_COLORS[session.architecture] || ARCHITECTURE_COLORS.CrewAI;
  const statusColor = getStatusColor(session.status);
  const isAwaitingResponse = session.status === 'running' && events[events.length - 1]?.event_type !== 'SYSTEM_END';
  const progressPercent =
    isStreaming && events.length > 0 ? Math.round((streamIndex / events.length) * 100) : session.progress;
  const phases = useMemo(() => detectPhases(events, session.status), [events, session.status]);
  const isResumed = useMemo(
    () => events.some(e => e.content?.includes('Resuming from checkpoint')),
    [events],
  );
  const resumedFromPhase = useMemo(() => {
    const e = events.find(e => e.content?.includes('Resuming from checkpoint'));
    return e?.metadata?.checkpoint_phase as number | undefined;
  }, [events]);

  return (
    <div className="flex h-full flex-1 flex-col bg-background">
      <div className="border-b border-border/50 bg-card/50 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <span
              className="rounded px-2 py-0.5 text-[10px] font-bold font-mono uppercase tracking-wider"
              style={{ color: archColor.text, backgroundColor: archColor.bg, border: `1px solid ${archColor.border}` }}
            >
              {session.architecture}
            </span>
            <h2 className="truncate text-sm font-semibold text-foreground">{session.research_topic}</h2>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1 rounded-md border border-border/30 px-1.5 py-0.5">
              {isStreaming ? (
                <button
                  onClick={stopStreaming}
                  className="p-0.5 text-amber-400 transition-colors hover:text-amber-300"
                  title="스트리밍 일시 정지"
                >
                  <Pause size={12} />
                </button>
              ) : (
                <button
                  onClick={startStreaming}
                  className="p-0.5 text-blue-500 transition-colors hover:text-blue-400"
                  title="스트리밍 시뮬레이션"
                >
                  <Play size={12} />
                </button>
              )}
              <button
                onClick={skipToEnd}
                className="p-0.5 text-muted-foreground transition-colors hover:text-foreground"
                title="전체 보기"
              >
                <SkipForward size={12} />
              </button>
            </div>

            <div className="flex items-center gap-1.5">
              <div className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: statusColor.dot }} />
              <span className="text-[10px] font-mono" style={{ color: statusColor.text }}>
                {getStatusLabel(session.status)}
              </span>
              {(session.status === 'running' || isStreaming) && <Radio size={10} className="animate-pulse-live text-blue-500" />}
            </div>

            {isAwaitingResponse && <WaitingIndicator compact />}

            <span className="text-[10px] font-mono text-muted-foreground">
              {filteredEvents.length}/{events.length} 이벤트
            </span>
          </div>
        </div>

        <div className="mt-2 h-1 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{
              width: `${progressPercent}%`,
              backgroundColor: archColor.text,
            }}
          />
        </div>
        <PhaseStepperRow phases={phases} isResumed={isResumed} resumedFromPhase={resumedFromPhase} />
      </div>

      <ArchitectureIdentityPanel session={session} events={events} />

      <div ref={scrollRef} onScroll={handleScroll} className="custom-scrollbar relative flex-1 overflow-y-auto py-2">
        {filteredEvents.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-muted-foreground">
            <p className="text-sm font-mono">표시할 로그가 없습니다</p>
            <p className="mt-1 text-xs">{isStreaming ? '스트리밍 중...' : '필터 조건을 확인해 주세요'}</p>
          </div>
        ) : (
          <>
            <AgentConversation events={filteredEvents} onEventClick={onEventClick} />
            {isAwaitingResponse && <WaitingIndicator />}
          </>
        )}
      </div>

      <button
        onClick={scrollToBottom}
        className="absolute right-4 bottom-4 z-10 flex h-8 w-8 items-center justify-center rounded-full border border-border bg-card text-muted-foreground shadow-sm transition-colors hover:border-blue-200 hover:text-foreground"
      >
        <ArrowDown size={14} />
      </button>
    </div>
  );
}
