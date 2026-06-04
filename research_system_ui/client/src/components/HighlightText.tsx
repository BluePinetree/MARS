/**
 * 키워드 하이라이트 컴포넌트
 * Design: Mission Control 테마 — 시안 하이라이트
 */

import { useMemo } from 'react';

interface HighlightTextProps {
  text: string;
  query: string;
  className?: string;
}

export default function HighlightText({ text, query, className = '' }: HighlightTextProps) {
  const parts = useMemo(() => {
    if (!query || query.length < 2) return [{ text, highlight: false }];
    const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    const splits = text.split(regex);
    return splits.map(part => ({
      text: part,
      highlight: regex.test(part),
    }));
  }, [text, query]);

  return (
    <span className={className}>
      {parts.map((part, i) =>
        part.highlight ? (
          <mark
            key={i}
            className="bg-blue-100 text-blue-700 rounded px-0.5"
          >
            {part.text}
          </mark>
        ) : (
          <span key={i}>{part.text}</span>
        )
      )}
    </span>
  );
}
