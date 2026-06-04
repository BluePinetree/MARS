/**
 * ContextInjectionInput — 실행 중 추가 컨텍스트 주입 입력창 (하단 고정)
 */

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Send, CheckCircle2 } from 'lucide-react';
import { injectContext } from '@/lib/api';

interface ContextInjectionInputProps {
  runId: string;
}

export default function ContextInjectionInput({ runId }: ContextInjectionInputProps) {
  const [context, setContext] = useState('');
  const [phase, setPhase] = useState('-1');
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  async function handleSend() {
    const trimmed = context.trim();
    if (!trimmed) return;
    setLoading(true);
    try {
      await injectContext(runId, trimmed, parseInt(phase));
      setContext('');
      setSent(true);
      setTimeout(() => setSent(false), 2000);
    } catch (e) {
      console.error('Context injection failed:', e);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="shrink-0 border-t border-border/50 bg-card/50 px-4 py-3">
      <div className="flex gap-2 items-end">
        <Textarea
          placeholder="실험 중 추가 정보 입력... (Ctrl+Enter로 전송)"
          value={context}
          onChange={(e) => setContext(e.target.value)}
          className="flex-1 text-sm resize-none h-14 min-h-0 bg-background border-border/50"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              handleSend();
            }
          }}
        />
        <div className="flex flex-col gap-1.5 shrink-0">
          <Select value={phase} onValueChange={setPhase}>
            <SelectTrigger className="h-7 text-xs w-[130px] font-mono">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="-1">모든 Phase</SelectItem>
              <SelectItem value="2">Phase 2 (코딩)</SelectItem>
              <SelectItem value="3">Phase 3 (실행)</SelectItem>
              <SelectItem value="4">Phase 4 (작성)</SelectItem>
            </SelectContent>
          </Select>
          <Button
            size="sm"
            className={`h-7 gap-1.5 text-xs font-mono transition-colors ${
              sent ? 'bg-emerald-600 hover:bg-emerald-700' : ''
            }`}
            disabled={loading || !context.trim()}
            onClick={handleSend}
          >
            {sent ? (
              <>
                <CheckCircle2 size={11} />
                전송됨
              </>
            ) : (
              <>
                <Send size={11} />
                전송
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
