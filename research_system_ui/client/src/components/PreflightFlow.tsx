/**
 * PreflightFlow — 실행 전 최대 4문항 확인 카드 (60초 타임아웃)
 */

import { useEffect, useCallback } from 'react';
import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Clock, ChevronRight, CheckCircle2, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Progress } from '@/components/ui/progress';
import { provideGuidance } from '@/lib/api';
import type { PreflightPayload } from '@/lib/types';
import { useCountdown } from '@/hooks/useCountdown';

interface PreflightFlowProps {
  runId: string;
  payload: PreflightPayload;
  onResolved: () => void;
}

export default function PreflightFlow({ runId, payload, onResolved }: PreflightFlowProps) {
  const choices = payload.choices ?? [];
  const hasChoices = choices.length > 0;
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(false);
  const [usedDefault, setUsedDefault] = useState(false);
  // 선택지 인덱스 또는 'custom'(직접 입력). 첫 항목(0)을 권장값으로 pre-select.
  const [selectedIdx, setSelectedIdx] = useState<number | 'custom'>(0);

  const handleExpire = useCallback(() => {
    setUsedDefault(true);
    setTimeout(onResolved, 1500);
  }, [onResolved]);

  const { remaining, ratio, start } = useCountdown(payload.timeout_secs || 60, handleExpire);

  // 질문이 바뀔 때마다 카운트다운 재시작
  useEffect(() => {
    setAnswer('');
    setUsedDefault(false);
    setSelectedIdx(0);
    start();
  }, [payload.question_key, start]);

  async function submitHint(hint: string) {
    setLoading(true);
    try {
      await provideGuidance(runId, {
        file_path: `preflight_${payload.question_key}`,
        user_action: 'provide_fix',
        hint: hint.trim() || payload.default,
      });
      onResolved();
    } catch {
      // 404나 오류 시에도 진행
      onResolved();
    } finally {
      setLoading(false);
    }
  }

  // "이대로 진행": 선택된 칩(또는 직접 입력값)을 힌트로 제출
  function handleContinue() {
    if (hasChoices && selectedIdx !== 'custom') {
      submitHint(choices[selectedIdx] ?? payload.default);
    } else {
      submitHint(answer);
    }
  }

  const canContinue = !loading && (!hasChoices || selectedIdx !== 'custom' || answer.trim().length > 0);

  const timeRatio = 1 - ratio;
  const isUrgent = remaining <= 10;

  if (usedDefault) {
    return (
      <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/20 backdrop-blur-[2px]">
        <div className="flex items-center gap-3 bg-card border border-border rounded-xl px-6 py-4 shadow-lg">
          <CheckCircle2 size={16} className="text-emerald-500" />
          <span className="text-sm text-muted-foreground font-mono">기본값으로 진행합니다...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/20 backdrop-blur-[2px]">
      <AnimatePresence mode="wait">
        <motion.div
          key={payload.question_key}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -20 }}
          transition={{ type: 'spring', stiffness: 380, damping: 30 }}
          className="w-full max-w-xl mx-4 bg-card border border-border rounded-xl shadow-xl overflow-hidden"
        >
          {/* 헤더 */}
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-border/50 bg-muted/30">
            <div className="flex items-center gap-2 text-xs font-mono text-muted-foreground">
              <Clock size={12} />
              <span>실행 전 확인</span>
            </div>
            <span className={`text-xs font-mono tabular-nums ${isUrgent ? 'text-red-500 animate-pulse' : 'text-amber-500'}`}>
              ⏱ {String(Math.floor(remaining / 60)).padStart(2, '0')}:{String(remaining % 60).padStart(2, '0')}
            </span>
          </div>

          <div className="px-5 py-4 space-y-4">
            {/* 질문 */}
            <p className="text-sm leading-relaxed text-foreground">{payload.question}</p>

            {/* 선택지(칩/라디오) 또는 자유 입력 */}
            {hasChoices ? (
              <div className="space-y-2">
                <div className="flex flex-col gap-1.5" role="radiogroup" aria-label="답변 선택">
                  {choices.map((c, i) => {
                    const active = selectedIdx === i;
                    return (
                      <button
                        key={i}
                        type="button"
                        role="radio"
                        aria-checked={active}
                        onClick={() => setSelectedIdx(i)}
                        className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs font-mono transition-colors ${
                          active
                            ? 'border-primary bg-primary/10 text-foreground'
                            : 'border-border/50 bg-background hover:bg-muted/50 text-muted-foreground'
                        }`}
                      >
                        <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${active ? 'border-primary bg-primary text-primary-foreground' : 'border-border'}`}>
                          {active && <Check size={11} />}
                        </span>
                        <span className="flex-1">{c}</span>
                        {i === 0 && <span className="text-[10px] text-emerald-500 shrink-0">추천</span>}
                      </button>
                    );
                  })}
                  <button
                    type="button"
                    role="radio"
                    aria-checked={selectedIdx === 'custom'}
                    onClick={() => setSelectedIdx('custom')}
                    className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs font-mono transition-colors ${
                      selectedIdx === 'custom'
                        ? 'border-primary bg-primary/10 text-foreground'
                        : 'border-border/50 bg-background hover:bg-muted/50 text-muted-foreground'
                    }`}
                  >
                    <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${selectedIdx === 'custom' ? 'border-primary bg-primary text-primary-foreground' : 'border-border'}`}>
                      {selectedIdx === 'custom' && <Check size={11} />}
                    </span>
                    <span className="flex-1">직접 입력…</span>
                  </button>
                </div>
                {selectedIdx === 'custom' && (
                  <Textarea
                    placeholder="답변을 직접 입력..."
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                    autoFocus
                    className="text-sm resize-none h-16 bg-background border-border/50 focus:border-primary/50"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) handleContinue();
                    }}
                  />
                )}
              </div>
            ) : (
              <>
                <div className="rounded-lg bg-muted/50 border border-border/40 px-3 py-2.5 text-xs text-muted-foreground font-mono">
                  <span className="text-muted-foreground/60 mr-2">추천:</span>
                  {payload.default}
                </div>
                <Textarea
                  placeholder="내 답변 입력..."
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                  className="text-sm resize-none h-20 bg-background border-border/50 focus:border-primary/50"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) handleContinue();
                  }}
                />
              </>
            )}

            {/* 타임아웃 프로그레스 바 */}
            <Progress
              value={timeRatio * 100}
              className={`h-1 transition-colors ${isUrgent ? '[&>div]:bg-red-500' : '[&>div]:bg-amber-400'}`}
            />
            <p className="text-[11px] text-muted-foreground text-right font-mono -mt-2">
              {remaining}초 후 추천값으로 진행
            </p>

            {/* 버튼 */}
            <div className="flex gap-2 pt-1">
              <Button
                variant="outline"
                size="sm"
                className="flex-1 text-xs font-mono"
                disabled={loading}
                onClick={() => submitHint(payload.default)}
              >
                추천값으로 진행
              </Button>
              <Button
                size="sm"
                className="flex-1 text-xs font-mono gap-1.5"
                disabled={!canContinue}
                onClick={handleContinue}
              >
                <ChevronRight size={12} />
                이대로 진행
              </Button>
            </div>
          </div>
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
