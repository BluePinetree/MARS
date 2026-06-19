/**
 * ApprovalDialog — Phase 1 plan approval gate.
 * Two-panel layout: plan overview (left) + file structure (right).
 * No tabs — both panels visible simultaneously.
 */

import { useState, useEffect, useRef } from 'react';
import { approvePlan } from '@/lib/api';
import type { ApprovalPayload } from '@/lib/types';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Clock, CheckCircle2, FileCode2, ChevronDown, ChevronRight,
  Layers, Play, AlertTriangle, XCircle, Loader2, HelpCircle,
} from 'lucide-react';

interface ApprovalDialogProps {
  runId: string;
  payload: ApprovalPayload;
  onResolved: () => void;
}

const STAGE_PALETTE = [
  { bg: 'bg-emerald-50', border: 'border-emerald-200', text: 'text-emerald-700', dot: 'bg-emerald-400', label: 'Config · Utils' },
  { bg: 'bg-blue-50',    border: 'border-blue-200',    text: 'text-blue-700',    dot: 'bg-blue-400',    label: 'Data · Model'  },
  { bg: 'bg-violet-50',  border: 'border-violet-200',  text: 'text-violet-700',  dot: 'bg-violet-400',  label: 'Entry Point'  },
];

const CRITERIA_COLORS = [
  'border-l-blue-400',
  'border-l-emerald-400',
  'border-l-violet-400',
  'border-l-amber-400',
  'border-l-rose-400',
  'border-l-cyan-400',
];

function useCountdown(seconds: number) {
  const [remaining, setRemaining] = useState(seconds);
  useEffect(() => {
    if (remaining <= 0) return;
    const id = setInterval(() => setRemaining(r => Math.max(0, r - 1)), 1000);
    return () => clearInterval(id);
  }, []);
  const m = Math.floor(remaining / 60);
  const s = remaining % 60;
  const pct = (remaining / seconds) * 100;
  return { remaining, label: `${m}:${String(s).padStart(2, '0')}`, pct, urgent: remaining < 120 };
}

export default function ApprovalDialog({ runId, payload, onResolved }: ApprovalDialogProps) {
  const [feedback, setFeedback]     = useState('');
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState('');
  const [action, setAction]         = useState<'modify' | 'reject' | null>(null);
  const [openStages, setOpenStages] = useState<Set<number>>(new Set([1, 2, 3]));
  const textareaRef                 = useRef<HTMLTextAreaElement>(null);
  const timer                       = useCountdown(payload.timeout_secs ?? 3600);

  const planner  = payload.plan?.planner;
  const designer = payload.plan?.designer;

  const filesByStage = (designer?.files ?? []).reduce<Record<number, typeof designer.files>>(
    (acc, f) => { const s = f.stage ?? 1; (acc[s] ??= []).push(f); return acc; },
    {},
  );
  const stages = Object.keys(filesByStage).map(Number).sort((a, b) => a - b);

  function toggleStage(s: number) {
    setOpenStages(prev => {
      const n = new Set(prev);
      n.has(s) ? n.delete(s) : n.add(s);
      return n;
    });
  }

  function selectAction(a: 'modify' | 'reject') {
    setAction(prev => prev === a ? null : a);
    setFeedback('');
    setError('');
    setTimeout(() => textareaRef.current?.focus(), 80);
  }

  async function submit(act: 'approve' | 'reject' | 'modify') {
    if ((act === 'reject' || act === 'modify') && !feedback.trim()) {
      setError('피드백을 입력해 주세요.');
      textareaRef.current?.focus();
      return;
    }
    setLoading(true);
    setError('');
    try {
      await approvePlan(runId, { action: act, feedback: feedback.trim() || undefined });
      onResolved();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes('404')) { onResolved(); return; }
      setError(msg);
      setLoading(false);
    }
  }

  return (
    <Dialog open>
      <DialogContent className="w-[90vw] h-[90vh] flex flex-col gap-0 p-0 overflow-hidden rounded-xl border-0 shadow-2xl [&>button]:hidden">

        {/* ── Header ───────────────────────────────────────────────────── */}
        <div className="shrink-0 px-6 pt-5 pb-4 border-b border-border/60 bg-gradient-to-r from-background to-muted/20">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-primary/10 border border-primary/20 shrink-0">
                <CheckCircle2 size={18} className="text-primary" />
              </div>
              <div className="min-w-0">
                <h2 className="text-base font-semibold text-foreground leading-none">
                  연구 계획 검토
                </h2>
                <p className="text-xs text-muted-foreground mt-1">
                  Phase 1 승인 대기 중 · Round {payload.round}
                  {planner?.recommended_profile && (
                    <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-primary/10 text-primary font-mono text-[10px] font-medium">
                      {planner.recommended_profile}
                    </span>
                  )}
                </p>
              </div>
            </div>

            {/* Countdown timer */}
            <div className={`shrink-0 flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-mono transition-colors ${
              timer.urgent
                ? 'bg-red-50 border-red-200 text-red-600'
                : 'bg-muted/60 border-border text-muted-foreground'
            }`}>
              <Clock size={12} className={timer.urgent ? 'animate-pulse' : ''} />
              {timer.label}
              <div className="w-16 h-1 rounded-full bg-border overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-1000 ${timer.urgent ? 'bg-red-400' : 'bg-primary'}`}
                  style={{ width: `${timer.pct}%` }}
                />
              </div>
            </div>
          </div>
        </div>

        {/* ── Two-panel body ───────────────────────────────────────────── */}
        <div className="flex-1 flex min-h-0 divide-x divide-border/60">

          {/* Left panel — Plan content */}
          <ScrollArea className="flex-[3] min-w-0 h-full">
            <div className="px-6 py-5 space-y-6">

              {/* Problem statement */}
              {planner?.problem_statement && (
                <section>
                  <SectionLabel icon={<HelpCircle size={11} />}>문제 정의</SectionLabel>
                  <blockquote className="mt-2 pl-4 border-l-[3px] border-primary/50 bg-primary/[0.03] rounded-r-lg py-3 pr-4">
                    <p className="text-sm text-foreground leading-relaxed">
                      {planner.problem_statement}
                    </p>
                  </blockquote>
                </section>
              )}

              {/* Success criteria */}
              {(planner?.success_criteria?.length ?? 0) > 0 && (
                <section>
                  <SectionLabel icon={<CheckCircle2 size={11} />}>
                    성공 기준 <span className="font-normal text-muted-foreground">({planner.success_criteria.length})</span>
                  </SectionLabel>
                  <ol className="mt-2 space-y-2">
                    {planner.success_criteria.map((c, i) => (
                      <li key={i} className={`flex gap-3 pl-3 border-l-2 py-2 pr-3 rounded-r-md bg-muted/30 hover:bg-muted/50 transition-colors ${CRITERIA_COLORS[i % CRITERIA_COLORS.length]}`}>
                        <span className="shrink-0 w-5 h-5 mt-0.5 rounded-full bg-background border border-border flex items-center justify-center text-[10px] font-bold text-muted-foreground">
                          {i + 1}
                        </span>
                        <span className="text-sm text-foreground leading-relaxed">{c}</span>
                      </li>
                    ))}
                  </ol>
                </section>
              )}

              {/* Hypotheses */}
              {(planner?.hypotheses?.length ?? 0) > 0 && (
                <section>
                  <SectionLabel icon={<Layers size={11} />}>가설</SectionLabel>
                  <ul className="mt-2 space-y-1.5">
                    {planner.hypotheses.map((h, i) => (
                      <li key={i} className="flex gap-2.5 text-sm text-muted-foreground">
                        <span className="shrink-0 mt-1.5 text-xs font-mono text-primary/60">H{i + 1}</span>
                        <span className="leading-relaxed">{h}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {/* Constraints */}
              {(planner?.constraints?.length ?? 0) > 0 && (
                <section>
                  <SectionLabel icon={<AlertTriangle size={11} />}>제약 조건</SectionLabel>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {planner.constraints.map((c, i) => (
                      <span
                        key={i}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-full bg-amber-50 border border-amber-200 text-amber-700 leading-relaxed"
                      >
                        <span className="w-1 h-1 rounded-full bg-amber-400 shrink-0" />
                        {c}
                      </span>
                    ))}
                  </div>
                </section>
              )}

              {/* Research questions */}
              {(planner?.research_questions?.length ?? 0) > 0 && (
                <section>
                  <SectionLabel icon={<HelpCircle size={11} />}>연구 질문</SectionLabel>
                  <ol className="mt-2 space-y-1.5">
                    {planner.research_questions.map((q, i) => (
                      <li key={i} className="flex gap-2.5 text-sm">
                        <span className="shrink-0 text-xs font-mono text-muted-foreground/60 mt-0.5">Q{i + 1}.</span>
                        <span className="text-muted-foreground leading-relaxed">{q}</span>
                      </li>
                    ))}
                  </ol>
                </section>
              )}

            </div>
          </ScrollArea>

          {/* Right panel — File structure */}
          <ScrollArea className="flex-[2] min-w-0 h-full">
            <div className="px-5 py-5 space-y-4">
              <SectionLabel icon={<FileCode2 size={11} />}>
                파일 구조 <span className="font-normal text-muted-foreground">({designer?.files?.length ?? 0}개)</span>
              </SectionLabel>

              {/* Entry point chip */}
              {designer?.entry_point && (
                <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-violet-200 bg-violet-50 text-xs">
                  <Play size={10} className="text-violet-500 shrink-0" fill="currentColor" />
                  <span className="text-violet-600 font-medium shrink-0">진입점</span>
                  <span className="text-violet-800 font-mono truncate">{designer.entry_point}</span>
                </div>
              )}

              {/* Stage accordion */}
              <div className="space-y-2">
                {stages.map((stage) => {
                  const files   = filesByStage[stage] ?? [];
                  const palette = STAGE_PALETTE[(stage - 1) % STAGE_PALETTE.length];
                  const isOpen  = openStages.has(stage);
                  return (
                    <div key={stage} className={`rounded-lg border overflow-hidden ${palette.bg} ${palette.border}`}>
                      <button
                        type="button"
                        onClick={() => toggleStage(stage)}
                        className="w-full flex items-center justify-between px-3.5 py-2.5 hover:bg-white/40 transition-colors"
                      >
                        <div className="flex items-center gap-2">
                          <span className={`w-2 h-2 rounded-full ${palette.dot} shrink-0`} />
                          <span className={`text-xs font-semibold ${palette.text}`}>
                            Stage {stage} · {palette.label}
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-[10px] text-muted-foreground font-mono">{files.length}파일</span>
                          {isOpen
                            ? <ChevronDown size={12} className="text-muted-foreground" />
                            : <ChevronRight size={12} className="text-muted-foreground" />}
                        </div>
                      </button>

                      {isOpen && (
                        <div className="border-t border-white/60">
                          {files.map((f, fi) => (
                            <div
                              key={f.path}
                              className={`px-3.5 py-2.5 ${fi > 0 ? 'border-t border-white/40' : ''} bg-white/50 hover:bg-white/80 transition-colors`}
                            >
                              <p className="text-[11px] font-mono text-foreground font-medium leading-none mb-1">
                                {f.path}
                              </p>
                              <p className="text-[11px] text-muted-foreground leading-relaxed">
                                {f.responsibility}
                              </p>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </ScrollArea>
        </div>

        {/* ── Feedback area (slides in when needed) ────────────────────── */}
        {action && (
          <div className="shrink-0 px-6 py-3 border-t border-border/60 bg-muted/20 space-y-2 animate-in slide-in-from-bottom-2 duration-200">
            <label className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              {action === 'reject'
                ? <><XCircle size={11} className="text-red-500" /> 거절 사유</>
                : <><AlertTriangle size={11} className="text-amber-500" /> 수정 요청 사항</>
              }
            </label>
            <Textarea
              ref={textareaRef}
              value={feedback}
              onChange={e => { setFeedback(e.target.value); setError(''); }}
              placeholder={action === 'reject'
                ? '계획의 어떤 부분이 적합하지 않은지 설명해 주세요.'
                : '어떤 방향으로 수정했으면 하는지 구체적으로 알려주세요.'}
              className="resize-none h-20 text-sm bg-background border-border focus-visible:ring-1 placeholder:text-muted-foreground/50"
            />
            {error && (
              <p className="flex items-center gap-1 text-xs text-red-500">
                <AlertTriangle size={10} /> {error}
              </p>
            )}
          </div>
        )}

        {/* ── Footer actions ───────────────────────────────────────────── */}
        <div className="shrink-0 flex items-center justify-between gap-3 px-6 py-4 border-t border-border/60 bg-background">
          <div className="flex items-center gap-2">
            {action ? (
              <Button
                variant="ghost"
                size="sm"
                disabled={loading}
                onClick={() => { setAction(null); setFeedback(''); setError(''); }}
                className="text-muted-foreground text-xs h-8"
              >
                ← 취소
              </Button>
            ) : (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={loading}
                  onClick={() => selectAction('modify')}
                  className="h-8 text-xs gap-1.5 text-amber-600 border-amber-300 hover:bg-amber-50 hover:border-amber-400"
                >
                  <AlertTriangle size={11} />
                  수정 요청
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={loading}
                  onClick={() => selectAction('reject')}
                  className="h-8 text-xs gap-1.5 text-red-500 hover:bg-red-50 hover:text-red-600"
                >
                  <XCircle size={11} />
                  거절
                </Button>
              </>
            )}
          </div>

          <div>
            {action ? (
              <Button
                size="sm"
                disabled={loading || !feedback.trim()}
                onClick={() => submit(action)}
                className={`h-8 text-xs px-5 gap-1.5 text-white ${
                  action === 'reject'
                    ? 'bg-red-500 hover:bg-red-600 disabled:bg-red-300'
                    : 'bg-amber-500 hover:bg-amber-600 disabled:bg-amber-300'
                }`}
              >
                {loading ? <Loader2 size={11} className="animate-spin" /> : null}
                {loading
                  ? '처리 중…'
                  : action === 'reject' ? '거절 확정' : '수정 요청 전송'}
              </Button>
            ) : (
              <Button
                size="sm"
                disabled={loading}
                onClick={() => submit('approve')}
                className="h-8 text-xs px-6 gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white font-medium"
              >
                {loading ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle2 size={11} />}
                {loading ? '처리 중…' : '승인'}
              </Button>
            )}
          </div>
        </div>

      </DialogContent>
    </Dialog>
  );
}

function SectionLabel({ children, icon }: { children: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-widest">
      {icon && <span className="opacity-60">{icon}</span>}
      {children}
    </div>
  );
}
