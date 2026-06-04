/**
 * Dashboard: session overview and research launch entrypoint.
 */

import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  ArrowRight,
  ChevronDown,
  ChevronUp,
  GitCompare,
  Plus,
  Radio,
  Trash2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { getSessions, type StartResearchRequest } from '@/lib/api';
import type { LogEvent, Session } from '@/lib/types';
import {
  analyzeLogEvents,
  getArchitectureProfile,
  getSessionSignature,
} from '@/lib/architecture';
import {
  ARCHITECTURE_COLORS,
  formatRelativeTime,
  getStatusColor,
  getStatusLabel,
  IMAGES,
} from '@/lib/constants';

interface DashboardProps {
  sessions: Session[];
  allLogs: Record<string, LogEvent[]>;
  onSelectSession: (runId: string) => void;
  onCompareView: () => void;
  onSessionsUpdate: (sessions: Session[]) => void;
  onStartResearch: (payload: StartResearchRequest) => Promise<void>;
  onDeleteSession: (runId: string) => Promise<void>;
}

interface ResearchFormState {
  topic: string;
  goal: string;
  domain: string;
  maxExperiments: string;
  timeLimitMinutes: string;
  preferredFrameworks: string;
  outputPath: string;
  dataPath: string;
  dataDescription: string;
}

const initialFormState: ResearchFormState = {
  topic: '',
  goal: '',
  domain: '',
  maxExperiments: '3',
  timeLimitMinutes: '60',
  preferredFrameworks: 'PyTorch, scikit-learn',
  outputPath: './outputs',
  dataPath: '',
  dataDescription: '',
};

export default function Dashboard({
  sessions,
  allLogs,
  onSelectSession,
  onCompareView,
  onSessionsUpdate,
  onStartResearch,
  onDeleteSession,
}: DashboardProps) {
  const completedSessions = sessions.filter((s) => s.status === 'completed');
  const architectureOverview = useMemo(() => {
    return (['CrewAI', 'AutoGen', 'LangGraph'] as const).map((architecture) => {
      const profile = getArchitectureProfile(architecture);
      const architectureSessions = sessions.filter((session) => session.architecture === architecture);
      const running = architectureSessions.filter((session) => session.status === 'running').length;
      const completed = architectureSessions.filter((session) => session.status === 'completed').length;
      const failed = architectureSessions.filter((session) => session.status === 'failed').length;
      const analytics = architectureSessions.reduce(
        (acc, session) => {
          const runAnalytics = analyzeLogEvents(allLogs[session.run_id] || []);
          acc.toolCalls += runAnalytics.toolCalls;
          acc.experimentResults += runAnalytics.experimentResults;
          acc.handoffs += runAnalytics.handoffs;
          acc.phaseCount += runAnalytics.phaseCount;
          acc.agentTurns += runAnalytics.agentTurns;
          return acc;
        },
        { toolCalls: 0, experimentResults: 0, handoffs: 0, phaseCount: 0, agentTurns: 0 },
      );

      return {
        architecture,
        profile,
        sessionCount: architectureSessions.length,
        running,
        completed,
        failed,
        analytics,
      };
    });
  }, [allLogs, sessions]);
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [deletingRunIds, setDeletingRunIds] = useState<string[]>([]);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [form, setForm] = useState<ResearchFormState>(initialFormState);

  const canSubmit = useMemo(
    () => !!form.topic.trim() && !isSubmitting,
    [form.topic, isSubmitting],
  );

  const handleFormChange = (key: keyof ResearchFormState, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmitResearch = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }

    setIsSubmitting(true);
    setSubmitError(null);

    const frameworks = form.preferredFrameworks
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);

    const payload: StartResearchRequest = {
      topic: form.topic.trim(),
      goal: form.goal.trim(),
      domain: form.domain.trim(),
      max_experiments: Number(form.maxExperiments) || 3,
      time_limit: Number(form.timeLimitMinutes) || 60,
      frameworks,
    };

    if (form.outputPath.trim()) {
      payload.output_path = form.outputPath.trim();
    }
    if (form.dataPath.trim()) {
      payload.data_path = form.dataPath.trim();
    }
    if (form.dataDescription.trim()) {
      payload.data_description = form.dataDescription.trim();
    }

    try {
      await onStartResearch(payload);
      setForm(initialFormState);
      setIsCreateDialogOpen(false);
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : '연구 시작 요청에 실패했습니다.');
    } finally {
      setIsSubmitting(false);
    }
  };

  useEffect(() => {
    let active = true;

    const refreshSessions = async () => {
      try {
        const nextSessions = await getSessions();
        if (active) {
          onSessionsUpdate(nextSessions);
        }
      } catch (error) {
        console.error('Failed to fetch sessions:', error);
      }
    };

    refreshSessions();
    const intervalId = window.setInterval(refreshSessions, 4000);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, [onSessionsUpdate]);

  const handleDeleteSession = async (runId: string) => {
    const target = sessions.find((session) => session.run_id === runId);
    if (!target) {
      return;
    }
    if (target.status === 'running') {
      window.alert('실행 중인 세션은 삭제할 수 없습니다.');
      return;
    }

    const confirmed = window.confirm(`세션을 삭제할까요?\nrun_id: ${runId}`);
    if (!confirmed) {
      return;
    }

    if (deletingRunIds.includes(runId)) {
      return;
    }
    setDeletingRunIds((prev) => [...prev, runId]);
    try {
      await onDeleteSession(runId);
    } catch (error) {
      const message = error instanceof Error ? error.message : '세션 삭제에 실패했습니다.';
      window.alert(message);
    } finally {
      setDeletingRunIds((prev) => prev.filter((id) => id !== runId));
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <div className="relative h-56 overflow-hidden">
        <img
          src={IMAGES.heroDashboard}
          alt=""
          className="absolute inset-0 w-full h-full object-cover opacity-40"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-background/30 via-background/60 to-background" />
        <div className="relative z-10 h-full flex flex-col justify-end px-8 pb-6">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse-live" />
            <span className="text-[10px] font-mono text-blue-500 uppercase tracking-widest">Research System</span>
          </div>
          <h1 className="text-2xl font-bold font-mono text-foreground tracking-tight">자율 연구 시스템 통합 대시보드</h1>
          <p className="text-sm text-muted-foreground mt-1">
            CrewAI, LangGraph, AutoGen 세션 실행 상태를 모니터링합니다.
          </p>
        </div>
      </div>

      <div className="px-8 py-3 border-b border-border/40 bg-card/30">
        <div className="flex items-center gap-5">
          <StatPill label="전체" value={sessions.length} color="#9CA3AF" />
          <div className="w-px h-5 bg-border/50" />
          <StatPill label="실행 중" value={sessions.filter((s) => s.status === 'running').length} color="#2563EB" pulse />
          <div className="w-px h-5 bg-border/50" />
          <StatPill label="완료" value={completedSessions.length} color="#10B981" />

          <div className="ml-auto flex items-center gap-2">
            <Dialog
              open={isCreateDialogOpen}
              onOpenChange={(open) => {
                if (!isSubmitting) {
                  setIsCreateDialogOpen(open);
                  if (open) {
                    setSubmitError(null);
                    setShowAdvanced(false);
                  }
                }
              }}
            >
              <DialogTrigger asChild>
                <Button
                  variant="outline"
                  className="h-8 px-3 border-blue-200 bg-blue-50 text-xs font-mono text-blue-600 hover:bg-blue-100"
                >
                  <Plus size={12} />
                  새 연구 시작
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-2xl">
                <DialogHeader>
                  <DialogTitle className="font-mono">새 연구 시작</DialogTitle>
                  <DialogDescription>
                    연구 주제만 입력하면 즉시 실행됩니다. 세부 설정이 필요하면 고급 설정을 펼치세요.
                  </DialogDescription>
                </DialogHeader>

                <form className="space-y-4" onSubmit={handleSubmitResearch}>
                  {/* ── Primary field ── */}
                  <div className="space-y-2">
                    <label className="text-xs font-mono text-muted-foreground">
                      연구 주제 <span className="text-blue-500">*</span>
                    </label>
                    <Input
                      value={form.topic}
                      onChange={(e) => handleFormChange('topic', e.target.value)}
                      placeholder="예: ResNet과 ViT의 CIFAR-100 성능 비교"
                      disabled={isSubmitting}
                      autoFocus
                    />
                  </div>

                  {/* ── Advanced settings toggle ── */}
                  <button
                    type="button"
                    onClick={() => setShowAdvanced((v) => !v)}
                    className="flex items-center gap-1.5 text-xs font-mono text-muted-foreground hover:text-foreground transition-colors select-none"
                  >
                    {showAdvanced ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                    고급 설정
                  </button>

                  {showAdvanced && (
                    <div className="space-y-4 rounded-xl border border-border/40 bg-muted/20 p-4">
                      <div className="space-y-2">
                        <label className="text-xs font-mono text-muted-foreground">연구 목표</label>
                        <Textarea
                          value={form.goal}
                          onChange={(e) => handleFormChange('goal', e.target.value)}
                          placeholder="예: 두 모델의 정확도, 학습 속도, 효율성 비교 분석"
                          rows={2}
                          disabled={isSubmitting}
                        />
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div className="space-y-2">
                          <label className="text-xs font-mono text-muted-foreground">연구 분야</label>
                          <Input
                            value={form.domain}
                            onChange={(e) => handleFormChange('domain', e.target.value)}
                            placeholder="예: 컴퓨터 비전"
                            disabled={isSubmitting}
                          />
                        </div>
                        <div className="space-y-2">
                          <label className="text-xs font-mono text-muted-foreground">출력 경로</label>
                          <Input
                            value={form.outputPath}
                            onChange={(e) => handleFormChange('outputPath', e.target.value)}
                            placeholder="./outputs"
                            disabled={isSubmitting}
                          />
                        </div>
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div className="space-y-2">
                          <label className="text-xs font-mono text-muted-foreground">최대 실험 횟수</label>
                          <Input
                            type="number"
                            min={1}
                            value={form.maxExperiments}
                            onChange={(e) => handleFormChange('maxExperiments', e.target.value)}
                            disabled={isSubmitting}
                          />
                        </div>
                        <div className="space-y-2">
                          <label className="text-xs font-mono text-muted-foreground">시간 제한 (분)</label>
                          <Input
                            type="number"
                            min={1}
                            value={form.timeLimitMinutes}
                            onChange={(e) => handleFormChange('timeLimitMinutes', e.target.value)}
                            disabled={isSubmitting}
                          />
                        </div>
                      </div>

                      <div className="space-y-2">
                        <label className="text-xs font-mono text-muted-foreground">선호 프레임워크 (쉼표 구분)</label>
                        <Input
                          value={form.preferredFrameworks}
                          onChange={(e) => handleFormChange('preferredFrameworks', e.target.value)}
                          placeholder="예: PyTorch, scikit-learn"
                          disabled={isSubmitting}
                        />
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div className="space-y-2">
                          <label className="text-xs font-mono text-muted-foreground">데이터셋 경로</label>
                          <Input
                            value={form.dataPath}
                            onChange={(e) => handleFormChange('dataPath', e.target.value)}
                            placeholder="선택사항"
                            disabled={isSubmitting}
                          />
                        </div>
                        <div className="space-y-2">
                          <label className="text-xs font-mono text-muted-foreground">데이터셋 설명</label>
                          <Input
                            value={form.dataDescription}
                            onChange={(e) => handleFormChange('dataDescription', e.target.value)}
                            placeholder="선택사항"
                            disabled={isSubmitting}
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  {submitError && <p className="text-xs font-mono text-red-400">{submitError}</p>}

                  <DialogFooter>
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={isSubmitting}
                      onClick={() => setIsCreateDialogOpen(false)}
                    >
                      취소
                    </Button>
                    <Button type="submit" disabled={!canSubmit}>
                      {isSubmitting ? '실행 시작 중...' : '실행 시작'}
                    </Button>
                  </DialogFooter>
                </form>
              </DialogContent>
            </Dialog>

            {completedSessions.length >= 2 && (
              <button
                onClick={onCompareView}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-blue-200 bg-blue-50 text-xs font-mono text-blue-600 hover:bg-blue-100 transition-colors"
              >
                <GitCompare size={12} />
                결과 비교
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="px-8 py-6">
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mb-6">
          {architectureOverview.map(({ architecture, profile, sessionCount, running, completed, failed, analytics }) => {
            const archColor = ARCHITECTURE_COLORS[architecture];
            return (
              <div
                key={architecture}
                className="rounded-2xl border border-border/50 bg-card p-5 shadow-sm"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <span
                      className="inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold font-mono uppercase tracking-wider"
                      style={{ color: archColor.text, backgroundColor: archColor.bg, border: `1px solid ${archColor.border}` }}
                    >
                      {architecture}
                    </span>
                    <h2 className="mt-3 text-base font-semibold font-mono text-foreground">{profile.label}</h2>
                    <p className="mt-1 text-xs text-muted-foreground">{profile.tagline}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Primary Focus</p>
                    <p className="mt-1 text-xs font-semibold" style={{ color: archColor.text }}>
                      {profile.primaryFocus}
                    </p>
                  </div>
                </div>

                <p className="mt-4 text-sm leading-6 text-foreground/80">{profile.summary}</p>

                <div className="mt-4 flex flex-wrap gap-2">
                  {profile.strengths.map((strength) => (
                    <span key={strength} className="rounded-full bg-muted/50 px-2 py-1 text-[10px] font-mono text-muted-foreground">
                      {strength}
                    </span>
                  ))}
                </div>

                <div className="mt-5 grid grid-cols-2 gap-3">
                  <div className="rounded-xl border border-border/30 bg-background/50 p-3">
                    <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Sessions</p>
                    <p className="mt-1 text-xl font-semibold font-mono text-foreground">{sessionCount}</p>
                    <p className="mt-1 text-[10px] font-mono text-muted-foreground">
                      {running} running / {completed} completed / {failed} failed
                    </p>
                  </div>
                  <div className="rounded-xl border border-border/30 bg-background/50 p-3">
                    <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Ops signal</p>
                    <p className="mt-1 text-xl font-semibold font-mono text-foreground">
                      {architecture === 'AutoGen'
                        ? analytics.agentTurns
                        : architecture === 'LangGraph'
                          ? analytics.phaseCount
                          : analytics.handoffs}
                    </p>
                    <p className="mt-1 text-[10px] font-mono text-muted-foreground">
                      {architecture === 'AutoGen'
                        ? 'conversation turns'
                        : architecture === 'LangGraph'
                          ? 'state transitions'
                          : 'role handoffs'}
                    </p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {sessions.map((session, index) => (
            <SessionCard
              key={session.run_id}
              session={session}
              logs={allLogs[session.run_id] || []}
              index={index}
              onClick={() => onSelectSession(session.run_id)}
              onDelete={() => handleDeleteSession(session.run_id)}
              isDeleting={deletingRunIds.includes(session.run_id)}
            />
          ))}
        </div>
      </div>

      {sessions.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20">
          <img src={IMAGES.emptyState} alt="" className="w-64 h-40 object-cover rounded-lg opacity-50 mb-6" />
          <p className="text-sm text-muted-foreground font-mono">아직 연구 세션이 없습니다</p>
          <p className="text-xs text-muted-foreground/60 mt-1">상단의 새 연구 시작 버튼으로 실행할 수 있습니다.</p>
        </div>
      )}
    </div>
  );
}

function StatPill({ label, value, color, pulse }: { label: string; value: number; color: string; pulse?: boolean }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-xl font-bold font-mono" style={{ color }}>{value}</span>
      <span className="text-[11px] text-muted-foreground/60">{label}</span>
      {pulse && value > 0 && <div className="w-1.5 h-1.5 rounded-full animate-pulse-live" style={{ backgroundColor: color }} />}
    </div>
  );
}

function SessionCard({
  session,
  logs,
  index,
  onClick,
  onDelete,
  isDeleting,
}: {
  session: Session;
  logs: LogEvent[];
  index: number;
  onClick: () => void;
  onDelete: () => void;
  isDeleting: boolean;
}) {
  const archColor = ARCHITECTURE_COLORS[session.architecture] || ARCHITECTURE_COLORS.CrewAI;
  const statusColor = getStatusColor(session.status);
  const canDelete = session.status !== 'running' && !isDeleting;
  const profile = getArchitectureProfile(session.architecture);
  const signature = getSessionSignature(session, logs);

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: Math.min(index * 0.06, 0.3) }}
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onClick();
        }
      }}
      role="button"
      tabIndex={0}
      className="text-left w-full rounded-xl border border-border/40 bg-card transition-all duration-200 overflow-hidden group cursor-pointer hover:border-border/70 hover:shadow-[0_4px_16px_rgba(0,0,0,0.08)]"
      style={{ '--arch-color': archColor.text } as React.CSSProperties}
    >
      {/* Top accent bar */}
      <div
        className="h-[2px] w-full opacity-0 group-hover:opacity-100 transition-opacity duration-300"
        style={{ background: `linear-gradient(to right, transparent, ${archColor.text}60, transparent)` }}
      />

      <div className="px-4 pt-3.5 pb-2">
        <div className="flex items-center justify-between mb-2.5">
          <span
            className="text-[10px] font-bold font-mono uppercase tracking-wider px-2 py-0.5 rounded-md"
            style={{ color: archColor.text, backgroundColor: archColor.bg, border: `1px solid ${archColor.border}` }}
          >
            {session.architecture}
          </span>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5">
              <div
                className="w-1.5 h-1.5 rounded-full"
                style={{ backgroundColor: statusColor.dot, boxShadow: session.status === 'running' ? `0 0 6px ${statusColor.dot}` : 'none' }}
              />
              <span className="text-[10px] font-mono" style={{ color: statusColor.text }}>
                {getStatusLabel(session.status)}
              </span>
              {session.status === 'running' && <Radio size={10} className="text-blue-500 animate-pulse-live" />}
            </div>
            <button
              type="button"
              onClick={(event) => { event.stopPropagation(); onDelete(); }}
              disabled={!canDelete}
              className="inline-flex items-center justify-center w-5 h-5 rounded text-muted-foreground/40 hover:text-red-400 disabled:opacity-25 disabled:cursor-not-allowed transition-colors"
              title={session.status === 'running' ? '실행 중인 세션은 삭제할 수 없습니다.' : '세션 삭제'}
              aria-label="세션 삭제"
            >
              <Trash2 size={10} />
            </button>
          </div>
        </div>

        <h3 className="text-sm font-semibold text-foreground mb-1 line-clamp-2 leading-snug tracking-tight">
          {session.research_topic}
        </h3>

        {session.status === 'failed' && session.error_summary ? (
          <p className="text-[10px] text-red-400/80 font-mono line-clamp-1 mt-1">{session.error_summary}</p>
        ) : (
          <p className="text-[11px] text-muted-foreground/60 line-clamp-1">{profile.tagline}</p>
        )}
      </div>

      {/* Progress */}
      <div className="px-4 pb-2.5">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[10px] text-muted-foreground/50 font-mono">진행률</span>
          <span className="text-[10px] font-mono font-semibold" style={{ color: archColor.text }}>
            {session.progress}%
          </span>
        </div>
        <div className="h-[3px] bg-muted/60 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{
              width: `${session.progress}%`,
              background: `linear-gradient(to right, ${archColor.text}90, ${archColor.text})`,
            }}
          />
        </div>
      </div>

      {/* Agents */}
      <div className="px-4 pb-3">
        <div className="flex flex-wrap gap-1">
          {session.agents.slice(0, 3).map((agent) => (
            <span key={agent} className="text-[9px] font-mono px-1.5 py-0.5 rounded-md bg-muted/40 text-muted-foreground/60">
              {agent}
            </span>
          ))}
          {session.agents.length > 3 && (
            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded-md bg-muted/40 text-muted-foreground/50">
              +{session.agents.length - 3}
            </span>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="px-4 py-2 border-t border-border/20 flex items-center justify-between">
        <div className="flex items-center gap-3 text-[10px] text-muted-foreground/40 font-mono">
          <span>{formatRelativeTime(session.start_time)}</span>
          <span>·</span>
          <span>{session.total_events} events</span>
        </div>
        <ArrowRight
          size={11}
          className="text-muted-foreground/30 group-hover:text-muted-foreground/70 transition-all group-hover:translate-x-0.5 duration-200"
        />
      </div>
    </motion.div>
  );
}
