/**
 * TerminalPane — Phase 3 실험 실행 중 stdout 스트리밍 뷰
 * 최대 5000줄 유지, 자동 스크롤 잠금 지원
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { ArrowDown, Terminal } from 'lucide-react';
import type { LogEvent } from '@/lib/types';

interface TerminalPaneProps {
  events: LogEvent[];
}

const MAX_LINES = 5000;

export default function TerminalPane({ events }: TerminalPaneProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  const lines = events
    .filter(e => e.event_type === 'exec_stdout')
    .map(e => e.content || '')
    .slice(-MAX_LINES);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines.length, autoScroll]);

  const handleScroll = useCallback(() => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 40);
  }, []);

  function scrollToBottom() {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
    setAutoScroll(true);
  }

  return (
    <div className="flex flex-col h-full border border-zinc-800 rounded-lg overflow-hidden" style={{ background: 'oklch(0.12 0 0)' }}>
      {/* 헤더 */}
      <div className="flex items-center justify-between px-3 py-2 bg-zinc-900 border-b border-zinc-800 shrink-0">
        <div className="flex items-center gap-2 text-xs font-mono text-zinc-400">
          <Terminal size={12} />
          <span>실험 실행 출력</span>
          <span className="text-zinc-600">({lines.length}줄)</span>
        </div>
        <button
          onClick={scrollToBottom}
          className={`flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded transition-colors ${
            autoScroll
              ? 'text-emerald-400 bg-emerald-400/10'
              : 'text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800'
          }`}
        >
          <ArrowDown size={10} />
          자동 스크롤
        </button>
      </div>

      {/* 출력 영역 */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-3 font-mono text-[11px] leading-relaxed custom-scrollbar"
        style={{ color: 'oklch(0.72 0.12 145)' }}
      >
        {lines.length === 0 ? (
          <div className="text-zinc-600 italic">실험 실행 대기 중...</div>
        ) : (
          lines.map((line, i) => (
            <div key={i} className="whitespace-pre-wrap break-all min-h-[1em]">
              {line}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
