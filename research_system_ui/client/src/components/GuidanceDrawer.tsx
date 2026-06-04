/**
 * GuidanceDrawer — Phase 2/3 repair loop 실패 시 사용자 개입 요청
 * 기존 배너 방식에서 오른쪽 Sheet Drawer로 전환
 * 로그 뷰가 Drawer 뒤에 계속 보여 컨텍스트 유지
 */

import { useState } from 'react';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { AlertTriangle } from 'lucide-react';
import { provideGuidance } from '@/lib/api';
import type { GuidancePayload } from '@/lib/types';

interface GuidanceDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  runId: string;
  payload: GuidancePayload | null;
  onResolved: () => void;
}

export default function GuidanceDrawer({
  open,
  onOpenChange,
  runId,
  payload,
  onResolved,
}: GuidanceDrawerProps) {
  const [hint, setHint] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  if (!payload) return null;

  const filePath = payload.entry ?? '';
  const shortPath = filePath.split(/[\\/]/).slice(-3).join('/');

  async function handleAction(action: 'continue' | 'skip' | 'provide_fix') {
    setLoading(true);
    setError('');
    try {
      await provideGuidance(runId, {
        file_path: filePath,
        user_action: action,
        hint: hint.trim() || undefined,
      });
      onResolved();
      onOpenChange(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes('404')) {
        onResolved();
        onOpenChange(false);
        return;
      }
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-[440px] max-w-[90vw] font-mono flex flex-col gap-0 p-0 overflow-hidden"
      >
        {/* 헤더 */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-border/50 bg-orange-50/60 shrink-0">
          <AlertTriangle size={14} className="text-orange-500" />
          <SheetHeader className="flex-1 p-0">
            <SheetTitle className="text-sm font-semibold text-orange-700">
              수동 개입 필요
            </SheetTitle>
          </SheetHeader>
          <Badge variant="outline" className="text-xs text-orange-600 border-orange-300 shrink-0">
            {payload.attempts}회 시도 후 실패
          </Badge>
        </div>

        {/* 내용 */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {/* 파일 경로 */}
          <div className="space-y-1.5">
            <p className="text-[11px] text-muted-foreground uppercase tracking-wide">파일</p>
            <code className="block text-xs text-cyan-700 bg-muted/50 px-2.5 py-1.5 rounded border border-border/50 break-all">
              {shortPath || filePath}
            </code>
          </div>

          {/* 진단 */}
          {payload.diagnosis && (
            <div className="space-y-1.5">
              <p className="text-[11px] text-muted-foreground uppercase tracking-wide">진단</p>
              <p className="text-xs text-foreground leading-relaxed">{payload.diagnosis}</p>
            </div>
          )}

          {/* 오류 메시지 */}
          {payload.error && (
            <div className="space-y-1.5">
              <p className="text-[11px] text-muted-foreground uppercase tracking-wide">오류</p>
              <pre className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2 overflow-x-auto whitespace-pre-wrap max-h-36 leading-relaxed">
                {payload.error}
              </pre>
            </div>
          )}

          {/* 힌트 입력 */}
          <div className="space-y-1.5">
            <p className="text-[11px] text-muted-foreground uppercase tracking-wide">힌트 (선택)</p>
            <Textarea
              placeholder="어떻게 고칠지 알고 있다면 입력하세요"
              value={hint}
              onChange={(e) => setHint(e.target.value)}
              className="text-xs resize-none h-20 bg-background"
            />
          </div>

          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>

        {/* 액션 버튼 */}
        <div className="px-5 py-4 border-t border-border/50 flex gap-2 shrink-0">
          <Button
            size="sm"
            className="flex-1 font-mono text-xs bg-orange-600 hover:bg-orange-700 text-white"
            disabled={loading}
            onClick={() => handleAction(hint.trim() ? 'provide_fix' : 'continue')}
          >
            {loading ? '처리 중...' : hint.trim() ? '힌트와 함께 재시도' : '재시도'}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="font-mono text-xs"
            disabled={loading}
            onClick={() => handleAction('skip')}
          >
            건너뛰기
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
