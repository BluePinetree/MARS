import type { ArchitectureType, LogEvent, Session } from './types';

export interface ArchitectureProfile {
  architecture: ArchitectureType;
  label: string;
  executionModel: string;
  tagline: string;
  summary: string;
  strengths: string[];
  primaryFocus: string;
}

export interface RunAnalytics {
  uniqueAgents: number;
  agentTurns: number;
  handoffs: number;
  toolCalls: number;
  toolResults: number;
  phaseCount: number;
  experimentStarts: number;
  experimentResults: number;
  codeBlocks: number;
  blockerCount: number;
  iterationCount: number;
}

export const ARCHITECTURE_PROFILES: Record<ArchitectureType, ArchitectureProfile> = {
  CrewAI: {
    architecture: 'CrewAI',
    label: 'Role Pipeline',
    executionModel: 'Role-based orchestration',
    tagline: '명확한 handoff와 반복 수정 루프',
    summary: '역할이 분리된 선형 파이프라인으로 안정성과 보고서 품질 관리에 강합니다.',
    strengths: ['Phase discipline', 'Repair loop', 'Report gating'],
    primaryFocus: 'Handoff stability',
  },
  AutoGen: {
    architecture: 'AutoGen',
    label: 'Dynamic Group Chat',
    executionModel: 'Selector-driven conversation',
    tagline: '다음 화자를 동적으로 고르는 협업형 토론',
    summary: '발화 선택과 자유로운 토론을 통해 탐색적 문제 해결과 아이디어 확장에 강합니다.',
    strengths: ['Speaker selection', 'Debate flow', 'Tool bursts'],
    primaryFocus: 'Conversation agility',
  },
  LangGraph: {
    architecture: 'LangGraph',
    label: 'State Workflow',
    executionModel: 'Explicit state graph',
    tagline: '노드와 조건 분기가 보이는 워크플로우',
    summary: '상태 전이와 조건 분기가 명시적이라 제어 가능성과 복구 경로 추적에 강합니다.',
    strengths: ['State transitions', 'Branch control', 'Loop visibility'],
    primaryFocus: 'Workflow control',
  },
};

function extractIterationNumber(event: LogEvent): number | null {
  const metadataIteration = event.metadata?.iteration;
  if (typeof metadataIteration === 'number' && Number.isFinite(metadataIteration)) {
    return metadataIteration;
  }
  if (typeof metadataIteration === 'string') {
    const parsed = Number.parseInt(metadataIteration, 10);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }

  const content = event.content || '';
  const patterns = [/iteration\s+(\d+)/i, /\biter(?:ation)?[_\s-]?(\d+)/i];
  for (const pattern of patterns) {
    const match = content.match(pattern);
    if (match) {
      const parsed = Number.parseInt(match[1], 10);
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
  }

  return null;
}

export function analyzeLogEvents(events: LogEvent[]): RunAnalytics {
  const uniqueAgents = new Set<string>();
  const iterations = new Set<number>();
  let agentTurns = 0;
  let handoffs = 0;
  let toolCalls = 0;
  let toolResults = 0;
  let phaseCount = 0;
  let experimentStarts = 0;
  let experimentResults = 0;
  let codeBlocks = 0;
  let blockerCount = 0;
  let previousSpeaker: string | null = null;

  events.forEach((event) => {
    const speaker = event.agent_name?.trim();
    if (speaker) {
      uniqueAgents.add(speaker);
    }

    const iteration = extractIterationNumber(event);
    if (iteration !== null) {
      iterations.add(iteration);
    }

    if (event.event_type === 'AGENT_MESSAGE' || event.event_type === 'AGENT_THINKING') {
      agentTurns += 1;
      if (speaker && previousSpeaker && previousSpeaker !== speaker) {
        handoffs += 1;
      }
      if (speaker) {
        previousSpeaker = speaker;
      }
    }

    if (event.event_type === 'TOOL_CALL') {
      toolCalls += 1;
    }
    if (event.event_type === 'TOOL_RESULT') {
      toolResults += 1;
    }
    if (event.event_type === 'PHASE_COMPLETE') {
      phaseCount += 1;
    }
    if (event.event_type === 'EXPERIMENT_START') {
      experimentStarts += 1;
    }
    if (event.event_type === 'EXPERIMENT_RESULT') {
      experimentResults += 1;
    }
    if (event.event_type === 'CODE_BLOCK') {
      codeBlocks += 1;
    }

    if (
      event.metadata?.active_blocker_type ||
      event.metadata?.failure_root_cause ||
      event.metadata?.blocker_fix_mode ||
      (event.content && /blocker|root cause|policy violated/i.test(event.content))
    ) {
      blockerCount += 1;
    }
  });

  return {
    uniqueAgents: uniqueAgents.size,
    agentTurns,
    handoffs,
    toolCalls,
    toolResults,
    phaseCount,
    experimentStarts,
    experimentResults,
    codeBlocks,
    blockerCount,
    iterationCount: iterations.size,
  };
}

export function getArchitectureProfile(architecture: ArchitectureType): ArchitectureProfile {
  return ARCHITECTURE_PROFILES[architecture] ?? ARCHITECTURE_PROFILES['CrewAI'];
}

export function getSessionSignature(
  session: Session,
  events: LogEvent[] = [],
): string[] {
  const analytics = analyzeLogEvents(events);
  const fallbackAgentCount = session.agents.length;

  switch (session.architecture) {
    case 'AutoGen':
      return [
        `${analytics.agentTurns || session.total_events} turns`,
        `${analytics.toolCalls} tools`,
        `${analytics.uniqueAgents || fallbackAgentCount} speakers`,
      ];
    case 'LangGraph':
      return [
        `${Math.max(analytics.phaseCount, analytics.iterationCount, 1)} states`,
        `${analytics.experimentResults || analytics.experimentStarts} runs`,
        `${analytics.blockerCount} blockers`,
      ];
    case 'CrewAI':
    default:
      return [
        `${analytics.uniqueAgents || fallbackAgentCount} roles`,
        `${Math.max(analytics.handoffs, analytics.phaseCount, 1)} handoffs`,
        `${analytics.experimentResults || analytics.experimentStarts} experiments`,
      ];
  }
}

export function getArchitectureSpotlight(
  session: Session,
  events: LogEvent[] = [],
): Array<{ label: string; value: string }> {
  const analytics = analyzeLogEvents(events);

  switch (session.architecture) {
    case 'AutoGen':
      return [
        { label: 'Conversation', value: `${analytics.agentTurns} turns` },
        { label: 'Selector activity', value: `${analytics.handoffs} speaker shifts` },
        { label: 'Tool burst', value: `${analytics.toolCalls} calls` },
      ];
    case 'LangGraph':
      return [
        { label: 'State transitions', value: `${Math.max(analytics.phaseCount, 1)}` },
        { label: 'Execution loops', value: `${Math.max(analytics.iterationCount, 1)}` },
        { label: 'Blockers seen', value: `${analytics.blockerCount}` },
      ];
    case 'CrewAI':
    default:
      return [
        { label: 'Role handoffs', value: `${Math.max(analytics.handoffs, 1)}` },
        { label: 'Phases closed', value: `${analytics.phaseCount}` },
        { label: 'Experiment cycles', value: `${analytics.experimentResults || analytics.experimentStarts}` },
      ];
  }
}
