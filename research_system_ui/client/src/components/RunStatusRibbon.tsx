/**
 * RunStatusRibbon — SessionView 상단 고정 실행 상태 리본
 * 실행 경과 시간, 현재 Phase, 체크포인트 재개 여부, repair 횟수 표시
 */

import { RotateCcw, Wrench, Radio } from 'lucide-react';
import type { Session, LogEvent } from '@/lib/types';
import { useElapsedTime } from '@/hooks/useElapsedTime';

interface RunStatusRibbonProps {
  session: Session;
  events: LogEvent[];
}

const PHASE_NAMES: Record<number, string> = {
  0: 'Workspace',
  1: 'Planning',
  2: 'Coding',
  3: 'Execution',
  4: 'Writing',
};

export default function RunStatusRibbon({ session, events }: RunStatusRibbonProps) {
  const elapsed = useElapsedTime(session.status === 'running' ? session.start_time : undefined);

  const resumeEvent = events.find(e => e.content?.includes('Resuming from checkpoint'));
  const isResumed = !!resumeEvent;
  const resumedFromPhase = resumeEvent?.metadata?.checkpoint_phase as number | undefined;

  const lastPhaseStart = events.filter(e => e.event_type === 'PHASE_START').at(-1);
  const currentPhase = lastPhaseStart?.metadata?.phase as number | undefined;

  const repairCount = events.filter(
    e => e.event_type === 'USER_GUIDANCE_RECEIVED' ||
      e.content?.toLowerCase().includes('[repair]')
  ).length;

  if (session.status !== 'running') return null;

  return (
    <div className="border-b border-border/40 bg-muted/30 px-4 py-1.5 shrink-0">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-0.5 text-[11px] font-mono">
        {/* Run ID */}
        <span className="text-foreground font-semibold tracking-tight">{session.run_id}</span>

        {/* 상태 표시 */}
        <span className="flex items-center gap-1 text-blue-500">
          <Radio size={9} className="animate-pulse-live" />
          실행 중
        </span>

        {/* 경과 시간 */}
        <span className="text-blue-400 tabular-nums">경과: {elapsed}</span>

        {/* 현재 Phase */}
        {currentPhase != null && (
          <span className="text-muted-foreground">
            Phase {currentPhase}
            {PHASE_NAMES[currentPhase] ? ` (${PHASE_NAMES[currentPhase]})` : ''} 진행 중
          </span>
        )}

        {/* 체크포인트 재개 */}
        {isResumed && (
          <span className="flex items-center gap-1 text-amber-500">
            <RotateCcw size={10} />
            재개됨{resumedFromPhase != null ? ` (P${resumedFromPhase})` : ''}
          </span>
        )}

        {/* Repair 횟수 */}
        {repairCount > 0 && (
          <span className="flex items-center gap-1 text-orange-400">
            <Wrench size={10} />
            {repairCount} repairs
          </span>
        )}
      </div>
    </div>
  );
}
