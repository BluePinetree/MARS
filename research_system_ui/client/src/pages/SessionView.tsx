/**
 * Session view: sidebar + live log view + detail panel
 * Sprint 3: 모든 신규 컴포넌트 통합 + 재진입 복원
 */

import { useEffect, useMemo, useState, useCallback } from 'react';
import { getLogs, streamLogs, getApprovalStatus, getGuidanceStatus } from '@/lib/api';
import type {
  LogEvent,
  FilterState,
  Session,
  SessionStatus,
  ApprovalPayload,
  GuidancePayload,
  PreflightPayload,
  TokenBudgetPayload,
  ExtensionProposalPayload,
} from '@/lib/types';
import Sidebar from '@/components/Sidebar';
import LogView from '@/components/LogView';
import DetailPanel from '@/components/DetailPanel';
import ApprovalDialog from '@/components/ApprovalDialog';
import GuidanceDrawer from '@/components/GuidanceDrawer';
import PreflightFlow from '@/components/PreflightFlow';
import TokenBudgetBar from '@/components/TokenBudgetBar';
import ProposalSheet from '@/components/ProposalSheet';
import RunStatusRibbon from '@/components/RunStatusRibbon';
import ContextInjectionInput from '@/components/ContextInjectionInput';
import TerminalPane from '@/components/TerminalPane';
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable';

interface SessionViewProps {
  sessions: Session[];
  allLogs: Record<string, LogEvent[]>;
  selectedRunId: string;
  onSelectSession: (runId: string) => void;
  onNewSession: (runId: string, topic: string, goal: string) => void;
  onGoHome: () => void;
  onLogsUpdate: (runId: string, updater: LogEvent[] | ((prev: LogEvent[]) => LogEvent[])) => void;
  onSessionStatusUpdate: (runId: string, status: SessionStatus, errorSummary?: string) => void;
}

function getLogEventKey(event: LogEvent): string {
  return [
    event.timestamp,
    event.run_id,
    event.event_type,
    event.agent_name || '',
    event.content || '',
    JSON.stringify(event.metadata || {}),
  ].join('|');
}

function mergeLogEvents(base: LogEvent[], incoming: LogEvent[]): LogEvent[] {
  if (incoming.length === 0) return base;
  const seen = new Set(base.map(getLogEventKey));
  const merged = [...base];
  incoming.forEach((event) => {
    const key = getLogEventKey(event);
    if (!seen.has(key)) {
      seen.add(key);
      merged.push(event);
    }
  });
  merged.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  return merged;
}

export default function SessionView({
  sessions,
  allLogs,
  selectedRunId,
  onSelectSession,
  onNewSession,
  onGoHome,
  onLogsUpdate,
  onSessionStatusUpdate,
}: SessionViewProps) {
  const [filters, setFilters] = useState<FilterState>({
    agents: [],
    eventTypes: [],
    searchQuery: '',
  });
  const [selectedEvent, setSelectedEvent] = useState<LogEvent | null>(null);

  // Gate 상태
  const [approvalPayload, setApprovalPayload] = useState<ApprovalPayload | null>(null);
  const [guidancePayload, setGuidancePayload] = useState<GuidancePayload | null>(null);
  const [guidanceOpen, setGuidanceOpen] = useState(false);
  const [preflightPayload, setPreflightPayload] = useState<PreflightPayload | null>(null);

  // 실시간 상태
  const [tokenBudgetPayload, setTokenBudgetPayload] = useState<TokenBudgetPayload | null>(null);
  const [proposalPayload, setProposalPayload] = useState<ExtensionProposalPayload | null>(null);
  const [proposalOpen, setProposalOpen] = useState(false);

  // 탭 전환 (로그 뷰 vs 터미널)
  const [activeTab, setActiveTab] = useState<'log' | 'terminal'>('log');

  const currentSession = sessions.find((s) => s.run_id === selectedRunId);
  const currentLogs = allLogs[selectedRunId] || [];

  // guidance 이벤트 라우팅: preflight_ → PreflightFlow, 나머지 → GuidanceDrawer
  const routeGuidanceEvent = useCallback((payload: GuidancePayload) => {
    if (payload.entry?.startsWith('preflight_')) {
      const key = payload.entry.replace('preflight_', '');
      // error_msg 형식: "Preflight question: {actual text}" — 프리픽스 제거
      const rawText = payload.diagnosis || payload.error || '';
      const question = rawText.replace(/^Preflight question:\s*/i, '') || key;
      setPreflightPayload({
        run_id: payload.run_id,
        question_key: key,
        question,
        default: '',  // 빈 값 → 백엔드가 자체 기본값 사용
        timeout_secs: 60,
        options: payload.options ?? [],
      });
    } else {
      setGuidancePayload(payload);
      setGuidanceOpen(true);
    }
  }, []);

  // PREFLIGHT_QUESTION 이벤트 → PreflightPayload 직접 파싱
  const handlePreflightQuestion = useCallback((event: LogEvent) => {
    const meta = event.metadata as Record<string, unknown>;
    setPreflightPayload({
      run_id: event.run_id,
      question_key: String(meta?.question_key ?? 'unknown'),
      question: String(meta?.question ?? event.content ?? ''),
      default: String(meta?.default ?? ''),
      timeout_secs: Number(meta?.timeout_secs ?? 60),
      options: (meta?.options as string[]) ?? [],
    });
  }, []);

  // 초기 로그 fetch
  useEffect(() => {
    let cancelled = false;
    async function fetchSessionLogs() {
      try {
        const fetchedLogs = await getLogs(selectedRunId);
        if (!cancelled) {
          onLogsUpdate(selectedRunId, (prev) => mergeLogEvents(prev, fetchedLogs));
        }
      } catch (error) {
        console.error(`Failed to fetch logs for run ${selectedRunId}:`, error);
      }
    }
    fetchSessionLogs();
    return () => { cancelled = true; };
  }, [onLogsUpdate, selectedRunId]);

  // 재진입 복원: 마운트 시 대기 중인 gate 상태 확인
  useEffect(() => {
    if (!currentSession || currentSession.status === 'completed' || currentSession.status === 'failed') return;

    async function restoreGateState() {
      try {
        const [approvalStatus, guidanceStatus] = await Promise.all([
          getApprovalStatus(selectedRunId),
          getGuidanceStatus(selectedRunId),
        ]);
        if (approvalStatus.awaiting_approval && approvalStatus.plan) {
          setApprovalPayload(approvalStatus.plan as unknown as ApprovalPayload);
        }
        if (guidanceStatus.awaiting_guidance && guidanceStatus.file_path) {
          const restored: GuidancePayload = {
            run_id: selectedRunId,
            entry: guidanceStatus.file_path,
            diagnosis: guidanceStatus.error ?? '',
            error: guidanceStatus.error ?? '',
            attempts: guidanceStatus.attempts ?? 0,
            options: guidanceStatus.options ?? [],
          };
          routeGuidanceEvent(restored);
        }
      } catch {
        // 재진입 복원 실패는 무시
      }
    }
    restoreGateState();
  }, [selectedRunId]); // eslint-disable-line react-hooks/exhaustive-deps

  // SSE 스트리밍
  useEffect(() => {
    if (!currentSession || currentSession.status === 'completed' || currentSession.status === 'failed') {
      return;
    }

    const stopStream = streamLogs(selectedRunId, {
      onEvent: (event) => {
        onLogsUpdate(selectedRunId, (prev) => mergeLogEvents(prev, [event]));

        switch (event.event_type) {
          case 'PLAN_AWAITING_APPROVAL':
            if (event.metadata) setApprovalPayload(event.metadata as unknown as ApprovalPayload);
            break;

          case 'USER_GUIDANCE_NEEDED': {
            const meta = event.metadata as Record<string, unknown>;
            if (meta?.file && !meta?.entry) meta.entry = meta.file;
            routeGuidanceEvent(meta as unknown as GuidancePayload);
            break;
          }

          case 'USER_GUIDANCE_RECEIVED':
            setGuidancePayload(null);
            setGuidanceOpen(false);
            setPreflightPayload(null);
            break;

          case 'PREFLIGHT_QUESTION':
            handlePreflightQuestion(event);
            break;

          case 'PREFLIGHT_ANSWERED':
            setPreflightPayload(null);
            break;

          case 'token_budget_snapshot':
          case 'token_budget_warning':
            if (event.metadata) {
              setTokenBudgetPayload({
                used: Number(event.metadata.used ?? 0),
                budget: Number(event.metadata.budget ?? 1),
                ratio: Number(event.metadata.ratio ?? 0),
                label: String(event.metadata.label ?? ''),
              });
            }
            break;

          case 'extension_proposals':
            if (event.metadata) {
              setProposalPayload({
                proposals: (event.metadata.proposals as string[]) ?? [],
                exec_success: Boolean(event.metadata.exec_success),
                metrics: (event.metadata.metrics as Record<string, unknown>) ?? {},
              });
              setProposalOpen(true);
            }
            break;

          case 'exec_stdout':
            // Phase 3 stdout → 터미널 탭 자동 전환
            setActiveTab('terminal');
            break;

          case 'PHASE_COMPLETE':
            // Phase 1 완료 또는 파이프라인 종료 시 approval dialog 닫기
            if (event.metadata?.phase === 1) setApprovalPayload(null);
            // Phase 3 완료 시 토큰 예산 바 숨기기
            if (event.metadata?.phase === 2) setTokenBudgetPayload(null);
            break;

          case 'SYSTEM_END':
            setApprovalPayload(null);
            break;
        }
      },
      onEnd: (event) => {
        onSessionStatusUpdate(selectedRunId, event.status);
      },
      onError: (error) => {
        console.error(`SSE stream error for run ${selectedRunId}:`, error);
      },
    });

    return () => { stopStream(); };
  }, [currentSession, onLogsUpdate, onSessionStatusUpdate, selectedRunId, routeGuidanceEvent, handlePreflightQuestion]);

  useEffect(() => {
    setSelectedEvent(null);
    setActiveTab('log');
  }, [selectedRunId]);

  const availableAgents = useMemo(() => {
    const agents = new Set<string>();
    currentLogs.forEach((event) => { if (event.agent_name) agents.add(event.agent_name); });
    return Array.from(agents);
  }, [currentLogs]);

  const hasStdout = useMemo(
    () => currentLogs.some(e => e.event_type === 'exec_stdout'),
    [currentLogs],
  );

  if (!currentSession) {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <p className="text-sm text-muted-foreground font-mono">세션을 찾을 수 없습니다.</p>
      </div>
    );
  }

  const isRunning = currentSession.status === 'running';

  return (
    <div className="flex h-screen bg-background overflow-hidden">
      {/* V4 Approval Dialog */}
      {approvalPayload && (
        <ApprovalDialog
          runId={selectedRunId}
          payload={approvalPayload}
          onResolved={() => setApprovalPayload(null)}
        />
      )}

      {/* Preflight Flow 오버레이 */}
      {preflightPayload && (
        <PreflightFlow
          runId={selectedRunId}
          payload={preflightPayload}
          onResolved={() => setPreflightPayload(null)}
        />
      )}

      {/* Guidance Drawer (Sheet) */}
      <GuidanceDrawer
        open={guidanceOpen && !!guidancePayload}
        onOpenChange={setGuidanceOpen}
        runId={selectedRunId}
        payload={guidancePayload}
        onResolved={() => { setGuidancePayload(null); setGuidanceOpen(false); }}
      />

      {/* Extension Proposals Bottom Sheet */}
      <ProposalSheet
        open={proposalOpen}
        onOpenChange={setProposalOpen}
        originalTopic={currentSession.research_topic}
        payload={proposalPayload}
        onNewRun={(newRunId, topic, goal) => onNewSession(newRunId, topic, goal)}
      />

      <Sidebar
        sessions={sessions}
        allLogs={allLogs}
        selectedRunId={selectedRunId}
        onSelectSession={onSelectSession}
        onGoHome={onGoHome}
        filters={filters}
        onFiltersChange={setFilters}
        availableAgents={availableAgents}
      />

      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        {/* 상단 실행 상태 리본 */}
        <RunStatusRibbon session={currentSession} events={currentLogs} />

        {/* Token Budget Bar (Phase 2 코딩 중에만) */}
        <TokenBudgetBar payload={tokenBudgetPayload} />

        {/* 로그 / 터미널 탭 (Phase 3 stdout 있을 때) */}
        {hasStdout && (
          <div className="flex items-center gap-1 px-4 py-1.5 border-b border-border/50 bg-muted/20 shrink-0">
            <button
              onClick={() => setActiveTab('log')}
              className={`px-3 py-1 rounded text-xs font-mono transition-colors ${
                activeTab === 'log'
                  ? 'bg-background border border-border/60 text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              이벤트 로그
            </button>
            <button
              onClick={() => setActiveTab('terminal')}
              className={`px-3 py-1 rounded text-xs font-mono transition-colors ${
                activeTab === 'terminal'
                  ? 'bg-background border border-border/60 text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              터미널
            </button>
          </div>
        )}

        {/* 메인 콘텐츠 */}
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
          {activeTab === 'terminal' ? (
            <div className="flex-1 min-h-0 p-3">
              <TerminalPane events={currentLogs} />
            </div>
          ) : selectedEvent ? (
            <ResizablePanelGroup direction="horizontal" autoSaveId="session-view-detail-layout" className="h-full">
              <ResizablePanel defaultSize={72} minSize={45}>
                <div className="h-full min-w-0 relative">
                  <LogView
                    session={currentSession}
                    events={currentLogs}
                    filters={filters}
                    onEventClick={setSelectedEvent}
                    searchQuery={filters.searchQuery}
                  />
                </div>
              </ResizablePanel>
              <ResizableHandle
                withHandle
                className="bg-border/70 transition-colors hover:bg-blue-300/50 data-[resize-handle-active]:bg-blue-300/70"
              />
              <ResizablePanel defaultSize={28} minSize={18} maxSize={45}>
                <DetailPanel event={selectedEvent} onClose={() => setSelectedEvent(null)} />
              </ResizablePanel>
            </ResizablePanelGroup>
          ) : (
            <div className="h-full relative">
              <LogView
                session={currentSession}
                events={currentLogs}
                filters={filters}
                onEventClick={setSelectedEvent}
                searchQuery={filters.searchQuery}
              />
            </div>
          )}
        </div>

        {/* 하단 컨텍스트 주입 입력 (실행 중에만) */}
        {isRunning && (
          <ContextInjectionInput runId={selectedRunId} />
        )}
      </div>
    </div>
  );
}
