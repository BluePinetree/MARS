/**
 * GuidancePanel — shown when Phase 2/3 repair loop is stuck and needs user input.
 */

import { useState } from 'react';
import { provideGuidance } from '@/lib/api';
import type { GuidancePayload } from '@/lib/types';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';

interface GuidancePanelProps {
  runId: string;
  payload: GuidancePayload;
  onResolved: () => void;
}

export default function GuidancePanel({ runId, payload, onResolved }: GuidancePanelProps) {
  const [hint, setHint]     = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError]   = useState('');

  // Normalize file path — show only the last 2–3 segments
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
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes('404')) { onResolved(); return; }
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-lg border border-orange-500 bg-zinc-900 font-mono text-sm">

      {/* Header bar */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-orange-500/40 bg-orange-950/60 rounded-t-lg">
        <span className="text-orange-400 font-bold">⚠</span>
        <span className="text-orange-300 font-semibold">수동 개입 필요</span>
        <span className="ml-auto text-xs text-orange-400/80 bg-orange-900/60 border border-orange-700 px-2 py-0.5 rounded">
          {payload.attempts}회 시도 후 실패
        </span>
      </div>

      <div className="px-4 py-3 space-y-3">

        {/* File path */}
        <div className="flex items-baseline gap-2">
          <span className="text-zinc-400 text-xs shrink-0">파일</span>
          <code className="text-cyan-300 text-xs bg-zinc-800 px-2 py-0.5 rounded border border-zinc-700">
            {shortPath || filePath}
          </code>
        </div>

        {/* Diagnosis */}
        {payload.diagnosis && (
          <div className="flex items-baseline gap-2">
            <span className="text-zinc-400 text-xs shrink-0">진단</span>
            <span className="text-zinc-200 text-xs">{payload.diagnosis}</span>
          </div>
        )}

        {/* Error message */}
        {payload.error && (
          <pre className="text-xs text-red-300 bg-zinc-950 border border-zinc-700 rounded px-3 py-2 overflow-x-auto whitespace-pre-wrap max-h-24 leading-relaxed">
            {payload.error}
          </pre>
        )}

        {/* Hint input */}
        <Textarea
          placeholder="힌트 (선택) — 어떻게 고칠지 알고 있다면 입력하세요"
          value={hint}
          onChange={(e) => setHint(e.target.value)}
          className="text-xs text-zinc-200 placeholder:text-zinc-500 bg-zinc-800 border-zinc-600 focus:border-orange-500 resize-none h-16"
        />

        {error && (
          <p className="text-xs text-red-400">{error}</p>
        )}

        {/* Actions */}
        <div className="flex items-center gap-2 pt-0.5">
          <Button
            size="sm"
            className="font-mono text-xs bg-orange-700 hover:bg-orange-600 text-white"
            disabled={loading}
            onClick={() => handleAction(hint.trim() ? 'provide_fix' : 'continue')}
          >
            {loading ? '처리 중...' : hint.trim() ? '힌트와 함께 재시도' : '재시도'}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="font-mono text-xs text-zinc-400 border-zinc-600 hover:bg-zinc-800 hover:text-zinc-200"
            disabled={loading}
            onClick={() => handleAction('skip')}
          >
            이 파일 건너뛰기
          </Button>
        </div>

      </div>
    </div>
  );
}
