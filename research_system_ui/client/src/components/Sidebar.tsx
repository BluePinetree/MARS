/**
 * 왼쪽 사이드바 — 세션 목록 + 필터/검색
 * Design: Mission Control 테마
 */

import { useState } from 'react';
import {
  Search, Filter, ChevronDown, ChevronRight, Radio,
  Home, X,
} from 'lucide-react';
import type { Session, EventType, FilterState, LogEvent } from '@/lib/types';
import { ARCHITECTURE_COLORS, getStatusColor, getStatusLabel, EVENT_TYPE_CONFIG } from '@/lib/constants';
import { getArchitectureProfile, getSessionSignature } from '@/lib/architecture';

interface SidebarProps {
  sessions: Session[];
  allLogs: Record<string, LogEvent[]>;
  selectedRunId: string | null;
  onSelectSession: (runId: string) => void;
  onGoHome: () => void;
  filters: FilterState;
  onFiltersChange: (filters: FilterState) => void;
  availableAgents: string[];
}

export default function Sidebar({
  sessions,
  allLogs,
  selectedRunId,
  onSelectSession,
  onGoHome,
  filters,
  onFiltersChange,
  availableAgents,
}: SidebarProps) {
  const [filtersOpen, setFiltersOpen] = useState(false);

  const handleSearchChange = (query: string) => {
    onFiltersChange({ ...filters, searchQuery: query });
  };

  const toggleAgent = (agent: string) => {
    const agents = filters.agents.includes(agent)
      ? filters.agents.filter(a => a !== agent)
      : [...filters.agents, agent];
    onFiltersChange({ ...filters, agents });
  };

  const toggleEventType = (type: EventType) => {
    const types = filters.eventTypes.includes(type)
      ? filters.eventTypes.filter(t => t !== type)
      : [...filters.eventTypes, type];
    onFiltersChange({ ...filters, eventTypes: types });
  };

  const clearFilters = () => {
    onFiltersChange({ agents: [], eventTypes: [], searchQuery: '' });
  };

  const hasActiveFilters = filters.agents.length > 0 || filters.eventTypes.length > 0 || filters.searchQuery.length > 0;

  return (
    <div className="w-72 h-full border-r border-border/50 bg-sidebar flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border/50">
        <button
          onClick={onGoHome}
          className="flex items-center gap-2 text-sm font-mono font-semibold text-sidebar-foreground hover:text-blue-600 transition-colors w-full"
        >
          <Home size={14} />
          <span>Mission Control</span>
        </button>
      </div>

      {/* Search */}
      <div className="px-3 py-2 border-b border-border/30">
        <div className="relative">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            placeholder="로그 검색..."
            value={filters.searchQuery}
            onChange={e => handleSearchChange(e.target.value)}
            className="w-full pl-7 pr-8 py-1.5 text-xs font-mono bg-input border border-border/50 rounded-md text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-ring"
          />
          {filters.searchQuery && (
            <button
              onClick={() => handleSearchChange('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X size={10} />
            </button>
          )}
        </div>
      </div>

      {/* Sessions List */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        <div className="px-3 py-2">
          <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider mb-2 px-1">
            세션 ({sessions.length})
          </p>
          <div className="space-y-1">
            {sessions.map(session => {
              const archColor = ARCHITECTURE_COLORS[session.architecture] || ARCHITECTURE_COLORS.CrewAI;
              const statusColor = getStatusColor(session.status);
              const isSelected = selectedRunId === session.run_id;
              const profile = getArchitectureProfile(session.architecture);
              const signature = getSessionSignature(session, allLogs[session.run_id] || []).slice(0, 2);

              return (
                <button
                  key={session.run_id}
                  onClick={() => onSelectSession(session.run_id)}
                  className={`w-full text-left rounded-lg px-3 py-2.5 transition-all duration-150 ${
                    isSelected
                      ? 'bg-sidebar-accent border border-sidebar-border'
                      : 'hover:bg-sidebar-accent/50 border border-transparent'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span
                      className="text-[9px] font-bold font-mono uppercase tracking-wider px-1.5 py-0.5 rounded"
                      style={{ color: archColor.text, backgroundColor: archColor.bg }}
                    >
                      {session.architecture}
                    </span>
                    <div className="flex items-center gap-1">
                      <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: statusColor.dot }} />
                      {session.status === 'running' && <Radio size={8} className="text-blue-500 animate-pulse-live" />}
                    </div>
                  </div>
                  <p className="text-xs text-sidebar-foreground line-clamp-1 mb-0.5">{session.research_topic}</p>
                  <p className="text-[10px] text-muted-foreground/80 line-clamp-2 mb-2">{profile.tagline}</p>
                  <div className="flex items-center justify-between">
                    <span className="text-[9px] text-muted-foreground font-mono">{getStatusLabel(session.status)}</span>
                    <span className="text-[9px] font-mono" style={{ color: archColor.text }}>{session.progress}%</span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {signature.map((item) => (
                      <span
                        key={item}
                        className="rounded-full px-1.5 py-0.5 text-[9px] font-mono"
                        style={{ color: archColor.text, backgroundColor: archColor.bg }}
                      >
                        {item}
                      </span>
                    ))}
                  </div>
                  {/* Mini progress bar */}
                  <div className="h-0.5 bg-muted rounded-full mt-1.5 overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${session.progress}%`, backgroundColor: archColor.text }}
                    />
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Filters Section */}
      <div className="border-t border-border/50">
        <button
          onClick={() => setFiltersOpen(!filtersOpen)}
          className="w-full flex items-center justify-between px-4 py-2.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <div className="flex items-center gap-2">
            <Filter size={12} />
            <span className="font-mono">필터</span>
            {hasActiveFilters && (
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
            )}
          </div>
          {filtersOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </button>

        {filtersOpen && (
          <div className="px-3 pb-3 space-y-3 max-h-64 overflow-y-auto custom-scrollbar">
            {/* Clear filters */}
            {hasActiveFilters && (
              <button
                onClick={clearFilters}
                className="text-[10px] text-blue-600 font-mono hover:underline"
              >
                필터 초기화
              </button>
            )}

            {/* Agent Filter */}
            {availableAgents.length > 0 && (
              <div>
                <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider mb-1.5">에이전트</p>
                <div className="space-y-0.5">
                  {availableAgents.map(agent => (
                    <label key={agent} className="flex items-center gap-2 px-1 py-0.5 rounded hover:bg-muted/30 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={filters.agents.length === 0 || filters.agents.includes(agent)}
                        onChange={() => toggleAgent(agent)}
                        className="w-3 h-3 rounded border-border bg-input accent-blue-600"
                      />
                      <span className="text-[10px] font-mono text-muted-foreground">{agent}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}

            {/* Event Type Filter */}
            <div>
              <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider mb-1.5">이벤트 유형</p>
              <div className="space-y-0.5">
                {(Object.keys(EVENT_TYPE_CONFIG) as EventType[]).map(type => (
                  <label key={type} className="flex items-center gap-2 px-1 py-0.5 rounded hover:bg-muted/30 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={filters.eventTypes.length === 0 || filters.eventTypes.includes(type)}
                      onChange={() => toggleEventType(type)}
                      className="w-3 h-3 rounded border-border bg-input accent-blue-600"
                    />
                    <span className="text-[10px] font-mono text-muted-foreground">{EVENT_TYPE_CONFIG[type].label}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
