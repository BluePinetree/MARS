/**
 * PreflightFlow — 실행 전 최대 4문항 확인 카드 (60초 타임아웃)
 */

import { useEffect, useCallback } from 'react';
import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Clock, ChevronRight, CheckCircle2 } from 'lucide-react';
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
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(false);
  const [usedDefault, setUsedDefault] = useState(false);

  const handleExpire = useCallback(() => {
    setUsedDefault(true);
    setTimeout(onResolved, 1500);
  }, [onResolved]);

  const { remaining, ratio, start } = useCountdown(payload.timeout_secs || 60, handleExpire);

  // 질문이 바뀔 때마다 카운트다운 재시작
  useEffect(() => {
    setAnswer('');
    setUsedDefault(false);
    start();
  }, [payload.question_key, start]);

  async function handleSubmit(useDefault: boolean) {
    setLoading(true);
    try {
      await provideGuidance(runId, {
        file_path: `preflight_${payload.question_key}`,
        user_action: 'provide_fix',
        hint: useDefault ? payload.default : (answer.trim() || payload.default),
      });
      onResolved();
    } catch {
      // 404나 오류 시에도 진행
      onResolved();
    } finally {
      setLoading(false);
    }
  }

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

            {/* 기본값 미리보기 */}
            <div className="rounded-lg bg-muted/50 border border-border/40 px-3 py-2.5 text-xs text-muted-foreground font-mono">
              <span className="text-muted-foreground/60 mr-2">기본값:</span>
              {payload.default}
            </div>

            {/* 답변 입력 */}
            <Textarea
              placeholder="내 답변 입력..."
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              className="text-sm resize-none h-20 bg-background border-border/50 focus:border-primary/50"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) handleSubmit(false);
              }}
            />

            {/* 타임아웃 프로그레스 바 */}
            <Progress
              value={timeRatio * 100}
              className={`h-1 transition-colors ${isUrgent ? '[&>div]:bg-red-500' : '[&>div]:bg-amber-400'}`}
            />
            <p className="text-[11px] text-muted-foreground text-right font-mono -mt-2">
              {remaining}초 후 기본값으로 진행
            </p>

            {/* 버튼 */}
            <div className="flex gap-2 pt-1">
              <Button
                variant="outline"
                size="sm"
                className="flex-1 text-xs font-mono"
                disabled={loading}
                onClick={() => handleSubmit(true)}
              >
                기본값으로 진행
              </Button>
              <Button
                size="sm"
                className="flex-1 text-xs font-mono gap-1.5"
                disabled={loading || !answer.trim()}
                onClick={() => handleSubmit(false)}
              >
                <ChevronRight size={12} />
                이 답변으로 계속
              </Button>
            </div>
          </div>
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
