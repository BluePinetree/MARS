/**
 * 자율 연구 시스템 통합 UI - 상수 및 유틸리티
 * Design: Mission Control 테마
 */

import type { AgentColor, EventType } from './types';

// 에이전트별 색상 코드 (V3 에이전트 기준 — light mode)
export const AGENT_COLORS: Record<string, AgentColor> = {
  // V3 agent roles
  'AI Research Planner': {
    name: 'Deep Blue',
    textColor: '#1D4ED8',
    bgColor: 'rgba(219, 234, 254, 0.7)',
    borderColor: 'rgba(37, 99, 235, 0.25)',
  },
  'Experiment Designer': {
    name: 'Purple',
    textColor: '#7C3AED',
    bgColor: 'rgba(237, 233, 254, 0.7)',
    borderColor: 'rgba(124, 58, 237, 0.25)',
  },
  'Research Code Engineer': {
    name: 'Green',
    textColor: '#047857',
    bgColor: 'rgba(209, 250, 229, 0.7)',
    borderColor: 'rgba(4, 120, 87, 0.25)',
  },
  'Experiment Executor': {
    name: 'Amber',
    textColor: '#B45309',
    bgColor: 'rgba(254, 243, 199, 0.7)',
    borderColor: 'rgba(180, 83, 9, 0.25)',
  },
  'Result Analyzer': {
    name: 'Teal',
    textColor: '#0F766E',
    bgColor: 'rgba(204, 251, 241, 0.7)',
    borderColor: 'rgba(15, 118, 110, 0.25)',
  },
  'Research Paper Writer': {
    name: 'Rose',
    textColor: '#BE123C',
    bgColor: 'rgba(255, 228, 230, 0.7)',
    borderColor: 'rgba(190, 18, 60, 0.25)',
  },
  'System': {
    name: 'Gray',
    textColor: '#4B5563',
    bgColor: 'rgba(243, 244, 246, 0.8)',
    borderColor: 'rgba(107, 114, 128, 0.2)',
  },
};

// 기본 에이전트 색상 (알 수 없는 에이전트용)
export const DEFAULT_AGENT_COLOR: AgentColor = {
  name: 'Default',
  textColor: '#6B7280',
  bgColor: 'rgba(243, 244, 246, 0.6)',
  borderColor: 'rgba(156, 163, 175, 0.3)',
};

// 이벤트 유형별 아이콘 및 레이블
export const EVENT_TYPE_CONFIG: Record<EventType, { label: string; icon: string }> = {
  SYSTEM_START: { label: '시스템 시작', icon: 'Play' },
  SYSTEM_END: { label: '시스템 종료', icon: 'Square' },
  AGENT_THINKING: { label: '에이전트 사고', icon: 'Brain' },
  AGENT_MESSAGE: { label: '에이전트 메시지', icon: 'MessageSquare' },
  TOOL_CALL: { label: '도구 호출', icon: 'Wrench' },
  TOOL_RESULT: { label: '도구 결과', icon: 'CheckCircle' },
  FILE_CREATED: { label: '파일 생성', icon: 'FileText' },
  CODE_BLOCK: { label: '코드 블록', icon: 'Code' },
  EXPERIMENT_START: { label: '실험 시작', icon: 'FlaskConical' },
  EXPERIMENT_RESULT: { label: '실험 결과', icon: 'BarChart3' },
  USER_QUESTION: { label: '사용자 질문', icon: 'HelpCircle' },
  PHASE_START: { label: '단계 시작', icon: 'ChevronRight' },
  PHASE_COMPLETE: { label: '단계 완료', icon: 'CheckCircle2' },
  WORKSPACE_GENERATION_START: { label: '워크스페이스 생성', icon: 'FolderOpen' },
  PLAN_AWAITING_APPROVAL: { label: '계획 승인 대기', icon: 'Clock' },
  USER_GUIDANCE_NEEDED: { label: '사용자 가이던스 필요', icon: 'AlertCircle' },
  USER_GUIDANCE_RECEIVED: { label: '가이던스 수신', icon: 'CheckCircle' },
  SECTION_DRAFT_DONE: { label: '섹션 초안 완료', icon: 'FileText' },
  PREFLIGHT_QUESTION: { label: '실행 전 확인', icon: 'HelpCircle' },
  PREFLIGHT_ANSWERED: { label: '확인 완료', icon: 'CheckCircle' },
  exec_stdout: { label: '실험 출력', icon: 'Terminal' },
  token_budget_warning: { label: '토큰 예산 경고', icon: 'AlertTriangle' },
  token_budget_snapshot: { label: '토큰 예산 스냅샷', icon: 'Activity' },
  failure_escalation: { label: '반복 실패 감지', icon: 'AlertOctagon' },
  extension_proposals: { label: '추가 실험 제안', icon: 'Lightbulb' },
  FILE_GENERATED: { label: '파일 생성됨', icon: 'CheckCircle2' },
  FILE_GENERATION_START: { label: '파일 생성 시작', icon: 'FileText' },
  FILE_GENERATION_FAILED: { label: '파일 생성 실패', icon: 'AlertTriangle' },
  FILE_SYNTAX_ERROR: { label: '구문 오류', icon: 'AlertTriangle' },
  FILE_IMPORT_ERROR: { label: '임포트 오류', icon: 'AlertTriangle' },
  FILE_FIXED: { label: '파일 수정 완료', icon: 'CheckCircle2' },
  SMOKE_TEST_START: { label: 'Smoke Test 시작', icon: 'FlaskConical' },
  SMOKE_TEST_DONE: { label: 'Smoke Test 완료', icon: 'FlaskConical' },
  SMOKE_TEST_SKIPPED: { label: 'Smoke Test 건너뜀', icon: 'FlaskConical' },
};

// 아키텍처 색상
export const ARCHITECTURE_COLORS: Record<string, { text: string; bg: string; border: string }> = {
  CrewAI: { text: '#2563EB', bg: 'rgba(37, 99, 235, 0.08)', border: 'rgba(37, 99, 235, 0.25)' },
  LangGraph: { text: '#D97706', bg: 'rgba(217, 119, 6, 0.08)', border: 'rgba(217, 119, 6, 0.25)' },
  AutoGen: { text: '#059669', bg: 'rgba(5, 150, 105, 0.08)', border: 'rgba(5, 150, 105, 0.25)' },
};

// 에이전트 색상 가져오기
export function getAgentColor(agentName?: string): AgentColor {
  if (!agentName) return AGENT_COLORS['System'] || DEFAULT_AGENT_COLOR;
  return AGENT_COLORS[agentName] || DEFAULT_AGENT_COLOR;
}

// 타임스탬프 포맷
export function formatTimestamp(ts: string): string {
  const date = new Date(ts);
  return date.toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

// 상대 시간 포맷
export function formatRelativeTime(ts: string): string {
  const now = new Date();
  const date = new Date(ts);
  const diff = now.getTime() - date.getTime();
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) return `${days}일 전`;
  if (hours > 0) return `${hours}시간 전`;
  if (minutes > 0) return `${minutes}분 전`;
  return '방금 전';
}

// 세션 상태 색상
export function getStatusColor(status: string): { text: string; bg: string; dot: string } {
  switch (status) {
    case 'queued':
      return { text: '#9333EA', bg: 'rgba(147, 51, 234, 0.1)', dot: '#9333EA' };
    case 'running':
      return { text: '#2563EB', bg: 'rgba(37, 99, 235, 0.1)', dot: '#2563EB' };
    case 'completed':
      return { text: '#059669', bg: 'rgba(5, 150, 105, 0.1)', dot: '#059669' };
    case 'failed':
      return { text: '#DC2626', bg: 'rgba(220, 38, 38, 0.1)', dot: '#DC2626' };
    case 'paused':
      return { text: '#D97706', bg: 'rgba(217, 119, 6, 0.1)', dot: '#D97706' };
    default:
      return { text: '#6B7280', bg: 'rgba(107, 114, 128, 0.1)', dot: '#6B7280' };
  }
}

// 상태 한글 레이블
export function getStatusLabel(status: string): string {
  switch (status) {
    case 'queued': return '대기 중';
    case 'running': return '실행 중';
    case 'completed': return '완료';
    case 'failed': return '실패';
    case 'paused': return '일시 중지';
    default: return status;
  }
}

// CDN 이미지 URL
export const IMAGES = {
  heroDashboard: 'https://d2xsxph8kpxj0f.cloudfront.net/111390107/oRYFL9RDhz9VskfybqGZR5/hero-dashboard-U4ZgX693KRC2Eya9FfpeoU.webp',
  emptyState: 'https://d2xsxph8kpxj0f.cloudfront.net/111390107/oRYFL9RDhz9VskfybqGZR5/empty-state-BkDZKcwYsrKTYMGjtiuRD2.webp',
  comparisonBg: 'https://d2xsxph8kpxj0f.cloudfront.net/111390107/oRYFL9RDhz9VskfybqGZR5/comparison-bg-UyECoePqMSGHvmQamCb3J3.webp',
};
