/**
 * ProposalSheet — Phase 4 완료 후 추가 실험 제안 Bottom Sheet
 */

import { useState } from 'react';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Lightbulb, Play, Loader2 } from 'lucide-react';
import type { ExtensionProposalPayload } from '@/lib/types';
import { acceptExtensionProposal } from '@/lib/api';

interface ProposalSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  originalTopic: string;
  payload: ExtensionProposalPayload | null;
  onNewRun?: (runId: string, topic: string, goal: string) => void;
}

export default function ProposalSheet({
  open,
  onOpenChange,
  originalTopic,
  payload,
  onNewRun,
}: ProposalSheetProps) {
  const [loadingIdx, setLoadingIdx] = useState<number | null>(null);

  if (!payload) return null;

  async function handleAccept(proposal: string, idx: number) {
    setLoadingIdx(idx);
    try {
      const goal = `[Extension] ${proposal}`;
      const { run_id } = await acceptExtensionProposal('', proposal, originalTopic);
      onNewRun?.(run_id, originalTopic, goal);
      onOpenChange(false);
    } catch (e) {
      console.error('Extension proposal failed:', e);
    } finally {
      setLoadingIdx(null);
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="h-auto max-h-[60vh] flex flex-col">
        <SheetHeader className="shrink-0">
          <SheetTitle className="flex items-center gap-2 text-sm">
            <Lightbulb size={14} className="text-blue-500" />
            추가 실험 제안
            <Badge variant="secondary" className="text-[10px] font-mono">
              {payload.proposals.length}개
            </Badge>
            {!payload.exec_success && (
              <Badge variant="destructive" className="text-[10px] font-mono ml-1">
                실험 실패
              </Badge>
            )}
          </SheetTitle>
          <SheetDescription className="text-xs">
            {payload.exec_success
              ? '실험이 성공적으로 완료됐습니다. 결과를 확장하는 추가 실험을 진행할 수 있습니다.'
              : '실험에서 문제가 감지됐습니다. 아래 제안으로 원인을 조사하거나 개선할 수 있습니다.'}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto space-y-2 pb-4 mt-2">
          {payload.proposals.map((proposal, i) => (
            <div
              key={i}
              className="flex items-center gap-3 rounded-lg border border-border/50 bg-muted/30 px-4 py-3 hover:bg-muted/50 transition-colors"
            >
              <p className="flex-1 text-sm leading-relaxed">{proposal}</p>
              <Button
                size="sm"
                variant="outline"
                className="shrink-0 gap-1.5 text-xs font-mono"
                disabled={loadingIdx !== null}
                onClick={() => handleAccept(proposal, i)}
              >
                {loadingIdx === i ? (
                  <Loader2 size={10} className="animate-spin" />
                ) : (
                  <Play size={10} />
                )}
                실행하기
              </Button>
            </div>
          ))}
        </div>
      </SheetContent>
    </Sheet>
  );
}
