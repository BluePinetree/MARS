/**
 * 자율 연구 시스템 통합 UI - 타입 정의
 * Design: Mission Control 테마 (다크 모드, 시안 액센트)
 */

// 이벤트 유형 정의
export type EventType =
  | 'SYSTEM_START'
  | 'SYSTEM_END'
  | 'AGENT_THINKING'
  | 'AGENT_MESSAGE'
  | 'TOOL_CALL'
  | 'TOOL_RESULT'
  | 'FILE_CREATED'
  | 'CODE_BLOCK'
  | 'EXPERIMENT_START'
  | 'EXPERIMENT_RESULT'
  | 'USER_QUESTION'
  | 'PHASE_START'
  | 'PHASE_COMPLETE'
  | 'WORKSPACE_GENERATION_START'
  // V4 interaction events
  | 'PLAN_AWAITING_APPROVAL'
  | 'USER_GUIDANCE_NEEDED'
  | 'USER_GUIDANCE_RECEIVED'
  | 'SECTION_DRAFT_DONE'
  // Sprint 1-4 신규 이벤트
  | 'PREFLIGHT_QUESTION'
  | 'PREFLIGHT_ANSWERED'
  | 'exec_stdout'
  | 'token_budget_warning'
  | 'token_budget_snapshot'
  | 'failure_escalation'
  | 'extension_proposals'
  // Phase 2 coding events
  | 'FILE_GENERATED'
  | 'FILE_GENERATION_START'
  | 'FILE_SYNTAX_ERROR'
  | 'FILE_IMPORT_ERROR'
  | 'FILE_FIXED'
  | 'FILE_GENERATION_FAILED'
  | 'SMOKE_TEST_START'
  | 'SMOKE_TEST_DONE'
  | 'SMOKE_TEST_SKIPPED';

// V4 Approval gate payload (inside LogEvent.metadata)
export interface ApprovalPayload {
  run_id: string;
  round: number;
  plan: {
    planner: {
      problem_statement: string;
      research_questions: string[];
      hypotheses: string[];
      success_criteria: string[];
      constraints: string[];
      recommended_profile: string;
    };
    designer: {
      entry_point: string;
      files: Array<{ path: string; responsibility: string; stage: number }>;
      generation_order: string[];
    };
  };
  timeout_secs: number;
}

// V4 Guidance gate payload (inside LogEvent.metadata)
export interface GuidancePayload {
  run_id: string;
  entry: string;
  diagnosis: string;
  error: string;
  attempts: number;
  options: string[];
}

// Sprint 1-4 신규 Payload 타입
export interface PreflightPayload {
  run_id: string;
  question_key: string;
  question: string;
  default: string;
  timeout_secs: number;
  options: string[];
}

export interface TokenBudgetPayload {
  used: number;
  budget: number;
  ratio: number;
  label?: string;
}

export interface FailureEscalationPayload {
  pattern_summary: string;
  kind: string;
}

export interface ExtensionProposalPayload {
  proposals: string[];
  exec_success: boolean;
  metrics: Record<string, unknown>;
}

// 세션 상태
export type SessionStatus = 'queued' | 'running' | 'completed' | 'failed' | 'paused';

// 아키텍처 유형
export type ArchitectureType = 'CrewAI' | 'LangGraph' | 'AutoGen';

// 로그 이벤트 메타데이터
export interface LogMetadata {
  status?: string;
  phase?: number;
  phase_number?: number;
  phase_name?: string;
  duration_ms?: number;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  success?: boolean;
  file_path?: string;
  language?: string;
  experiment_id?: string;
  metrics?: Record<string, number>;
  figures?: string[];
  artifact_paths?: string[];
  status_snapshot?: Record<string, unknown>;
  failure_fingerprint?: string;
  failure_repeat_count?: number;
  failure_root_cause?: string;
  blocker_fix_mode?: boolean;
  active_blocker_type?: string;
  active_blocker_root_cause?: string;
  error?: string;
  summary?: string;
  [key: string]: unknown;
}

// 표준 로그 이벤트
export interface LogEvent {
  timestamp: string;
  session_id: string;
  run_id: string;
  event_type: EventType;
  agent_name?: string;
  content?: string;
  metadata?: LogMetadata;
}

// 세션 정보
export interface Session {
  run_id: string;
  session_id: string;
  research_topic: string;
  architecture: ArchitectureType;
  status: SessionStatus;
  progress: number;
  start_time: string;
  end_time?: string;
  error_summary?: string;
  total_events: number;
  agents: string[];
}

// 에이전트 색상 정보
export interface AgentColor {
  name: string;
  textColor: string;
  bgColor: string;
  borderColor: string;
}

// 필터 상태
export interface FilterState {
  agents: string[];
  eventTypes: EventType[];
  searchQuery: string;
}

// 비교 뷰 데이터
export interface ComparisonData {
  session: Session;
  metrics: Record<string, number>;
  report?: string;
}
