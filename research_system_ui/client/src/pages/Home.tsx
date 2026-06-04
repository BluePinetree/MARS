/**
 * Home — 메인 앱 컨트롤러
 * Design: Mission Control 테마
 * 대시보드 / 세션 뷰 / 비교 뷰 간 라우팅
 */

import { useCallback, useState } from 'react';
import { deleteSession, startResearch, type StartResearchRequest } from '@/lib/api';
import type { LogEvent, Session, SessionStatus } from '@/lib/types';
import Dashboard from './Dashboard';
import SessionView from './SessionView';
import ComparisonView from './ComparisonView';

type ViewMode = 'dashboard' | 'session' | 'comparison';
type LogsUpdater = LogEvent[] | ((prev: LogEvent[]) => LogEvent[]);

export default function Home() {
  const [viewMode, setViewMode] = useState<ViewMode>('dashboard');
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [allLogs, setAllLogs] = useState<Record<string, LogEvent[]>>({});

  const handleSelectSession = (runId: string) => {
    setSelectedRunId(runId);
    setViewMode('session');
  };

  const handleGoHome = () => {
    setViewMode('dashboard');
    setSelectedRunId(null);
  };

  const handleCompareView = () => {
    setViewMode('comparison');
  };

  const handleSessionsUpdate = useCallback((nextSessions: Session[]) => {
    setSessions(nextSessions);
  }, []);

  const handleLogsUpdate = useCallback((runId: string, updater: LogsUpdater) => {
    setAllLogs((prev) => {
      const prevLogs = prev[runId] || [];
      const nextLogs = typeof updater === 'function' ? updater(prevLogs) : updater;
      return { ...prev, [runId]: nextLogs };
    });
  }, []);

  const handleSessionStatusUpdate = useCallback((runId: string, status: SessionStatus, errorSummary?: string) => {
    setSessions((prev) =>
      prev.map((session) => {
        if (session.run_id !== runId) {
          return session;
        }
        return {
          ...session,
          status,
          error_summary: errorSummary ?? session.error_summary,
        };
      }),
    );
  }, []);

  const handleStartResearch = useCallback(async (payload: StartResearchRequest) => {
    const result = await startResearch(payload);
    const now = new Date().toISOString();

    setSessions((prev) => {
      const nextSession: Session = {
        run_id: result.run_id,
        session_id: result.session_id,
        research_topic: payload.topic,
        architecture: 'CrewAI',
        status: result.status as SessionStatus,
        progress: 0,
        start_time: now,
        total_events: 0,
        agents: ['System'],
      };

      const exists = prev.some((session) => session.run_id === result.run_id);
      if (exists) {
        return prev.map((session) =>
          session.run_id === result.run_id ? { ...session, ...nextSession } : session,
        );
      }
      return [nextSession, ...prev];
    });

    setAllLogs((prev) => (prev[result.run_id] ? prev : { ...prev, [result.run_id]: [] }));
    setSelectedRunId(result.run_id);
    setViewMode('session');
  }, []);

  const handleNewSession = useCallback((runId: string, topic: string, _goal: string) => {
    const now = new Date().toISOString();
    const nextSession: Session = {
      run_id: runId,
      session_id: runId,
      research_topic: topic,
      architecture: 'CrewAI',
      status: 'queued',
      progress: 0,
      start_time: now,
      total_events: 0,
      agents: ['System'],
    };
    setSessions((prev) => {
      if (prev.some((s) => s.run_id === runId)) return prev;
      return [nextSession, ...prev];
    });
    setAllLogs((prev) => (prev[runId] ? prev : { ...prev, [runId]: [] }));
    setSelectedRunId(runId);
    setViewMode('session');
  }, []);

  const handleDeleteSession = useCallback(async (runId: string) => {
    await deleteSession(runId);

    setSessions((prev) => prev.filter((session) => session.run_id !== runId));
    setAllLogs((prev) => {
      if (!(runId in prev)) {
        return prev;
      }
      const next = { ...prev };
      delete next[runId];
      return next;
    });

    if (selectedRunId === runId) {
      setSelectedRunId(null);
      setViewMode('dashboard');
    }
  }, [selectedRunId]);

  switch (viewMode) {
    case 'session':
      return (
        <SessionView
          sessions={sessions}
          allLogs={allLogs}
          selectedRunId={selectedRunId!}
          onSelectSession={handleSelectSession}
          onNewSession={handleNewSession}
          onGoHome={handleGoHome}
          onLogsUpdate={handleLogsUpdate}
          onSessionStatusUpdate={handleSessionStatusUpdate}
        />
      );
    case 'comparison':
      return (
        <ComparisonView
          sessions={sessions}
          allLogs={allLogs}
          onBack={handleGoHome}
        />
      );
    default:
      return (
        <Dashboard
          sessions={sessions}
          allLogs={allLogs}
          onSelectSession={handleSelectSession}
          onCompareView={handleCompareView}
          onSessionsUpdate={handleSessionsUpdate}
          onStartResearch={handleStartResearch}
          onDeleteSession={handleDeleteSession}
        />
      );
  }
}
