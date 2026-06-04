/**
 * TokenBudgetBar — Phase 2 코딩 중 토큰 예산 사용량 표시
 */

import { Progress } from '@/components/ui/progress';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { AlertTriangle } from 'lucide-react';
import type { TokenBudgetPayload } from '@/lib/types';

interface TokenBudgetBarProps {
  payload: TokenBudgetPayload | null;
}

export default function TokenBudgetBar({ payload }: TokenBudgetBarProps) {
  if (!payload) return null;

  const percent = Math.min(Math.round(payload.ratio * 100), 100);
  const isWarning = percent >= 80;
  const isCritical = percent >= 100;

  const indicatorColor = isCritical
    ? '[&>[data-slot=progress-indicator]]:bg-red-500'
    : isWarning
      ? '[&>[data-slot=progress-indicator]]:bg-amber-500'
      : '';

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            className={`flex items-center gap-3 px-4 py-1.5 border-b border-border/50 cursor-default ${
              isCritical ? 'bg-red-50/60' : isWarning ? 'bg-amber-50/50' : 'bg-muted/20'
            }`}
          >
            <span className="text-[11px] font-mono text-muted-foreground shrink-0 select-none">
              Phase 2 코딩 중
            </span>
            <Progress
              value={percent}
              className={`h-1.5 flex-1 transition-all ${indicatorColor}`}
            />
            <span
              className={`text-[11px] font-mono tabular-nums shrink-0 ${
                isCritical ? 'text-red-500 font-semibold' : isWarning ? 'text-amber-500' : 'text-muted-foreground'
              }`}
            >
              {percent}%
            </span>
            {isWarning && (
              <AlertTriangle size={11} className={isCritical ? 'text-red-500' : 'text-amber-500'} />
            )}
          </div>
        </TooltipTrigger>
        <TooltipContent side="bottom" className="max-w-xs text-xs">
          <p>LLM이 파일 간 의존성을 학습하는 데 사용한 컨텍스트 크기입니다.</p>
          {isCritical && (
            <p className="mt-1 text-red-400 font-semibold">
              의존성 컨텍스트 한계 도달 — LLM 입력이 절단되고 있습니다.
            </p>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
