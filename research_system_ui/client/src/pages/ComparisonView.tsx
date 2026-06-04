/**
 * 결과 비교 뷰 — 완료된 프로토타입의 최종 결과를 나란히 비교
 * Design: Mission Control 테마 — Recharts 바 차트 포함
 */

import { useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, BarChart3, Clock, Cpu, HardDrive, Trophy, TrendingUp } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar } from 'recharts';
import type { LogEvent, Session } from '@/lib/types';
import { ARCHITECTURE_COLORS, IMAGES } from '@/lib/constants';
import { analyzeLogEvents, getArchitectureProfile, getSessionSignature } from '@/lib/architecture';

interface ComparisonViewProps {
  sessions: Session[];
  allLogs: Record<string, LogEvent[]>;
  onBack: () => void;
}

type ChartMode = 'bar' | 'radar';

export default function ComparisonView({ sessions, allLogs, onBack }: ComparisonViewProps) {
  const [chartMode, setChartMode] = useState<ChartMode>('bar');
  const completedSessions = sessions.filter(s => s.status === 'completed' || s.status === 'paused');

  const sessionResults = useMemo(() => {
    return completedSessions.map(session => {
      const logs = allLogs[session.run_id] || [];
      const experimentResults = logs.filter(e => e.event_type === 'EXPERIMENT_RESULT');
      const allMetrics: Record<string, number> = {};
      experimentResults.forEach(result => {
        if (result.metadata?.metrics) {
          Object.entries(result.metadata.metrics).forEach(([key, value]) => {
            allMetrics[key] = value;
          });
        }
      });
      return {
        session,
        metrics: allMetrics,
        resultCount: experimentResults.length,
        analytics: analyzeLogEvents(logs),
        signature: getSessionSignature(session, logs),
        profile: getArchitectureProfile(session.architecture),
      };
    });
  }, [completedSessions, allLogs]);

  const allMetricKeys = useMemo(() => {
    const keys = new Set<string>();
    sessionResults.forEach(r => Object.keys(r.metrics).forEach(k => keys.add(k)));
    return Array.from(keys);
  }, [sessionResults]);

  const bestMetrics = useMemo(() => {
    const best: Record<string, { value: number; runId: string }> = {};
    allMetricKeys.forEach(key => {
      const isLowerBetter = key.includes('loss') || key.includes('time') || key.includes('memory') || key.includes('flops');
      let bestVal = isLowerBetter ? Infinity : -Infinity;
      let bestRunId = '';
      sessionResults.forEach(r => {
        const val = r.metrics[key];
        if (val !== undefined) {
          if (isLowerBetter ? val < bestVal : val > bestVal) {
            bestVal = val;
            bestRunId = r.session.run_id;
          }
        }
      });
      best[key] = { value: bestVal, runId: bestRunId };
    });
    return best;
  }, [allMetricKeys, sessionResults]);

  // Recharts 데이터 준비
  const chartData = useMemo(() => {
    return allMetricKeys.map(key => {
      const row: Record<string, string | number> = { metric: key.replace(/_/g, ' ') };
      sessionResults.forEach(r => {
        row[r.session.architecture] = r.metrics[key] ?? 0;
      });
      return row;
    });
  }, [allMetricKeys, sessionResults]);

  // Radar 차트용 정규화 데이터
  const radarData = useMemo(() => {
    const normalizedKeys = allMetricKeys.filter(k => {
      return sessionResults.some(r => r.metrics[k] !== undefined);
    });
    return normalizedKeys.map(key => {
      const isLowerBetter = key.includes('loss') || key.includes('time') || key.includes('memory') || key.includes('flops');
      const values = sessionResults.map(r => r.metrics[key]).filter(v => v !== undefined);
      const maxVal = Math.max(...values, 1);
      const row: Record<string, string | number> = { metric: key.replace(/_/g, ' ') };
      sessionResults.forEach(r => {
        const val = r.metrics[key];
        if (val !== undefined) {
          row[r.session.architecture] = isLowerBetter
            ? Math.round(((maxVal - val) / maxVal) * 100)
            : Math.round((val / maxVal) * 100);
        } else {
          row[r.session.architecture] = 0;
        }
      });
      return row;
    });
  }, [allMetricKeys, sessionResults]);

  const archColors = sessionResults.map(r => ARCHITECTURE_COLORS[r.session.architecture]?.text || '#2563EB');

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="relative h-40 overflow-hidden">
        <img src={IMAGES.comparisonBg} alt="" className="absolute inset-0 w-full h-full object-cover opacity-30" />
        <div className="absolute inset-0 bg-gradient-to-b from-background/30 via-background/60 to-background" />
        <div className="relative z-10 h-full flex flex-col justify-end px-8 pb-4">
          <button
            onClick={onBack}
            className="flex items-center gap-1.5 text-xs font-mono text-muted-foreground hover:text-[#2563EB] transition-colors mb-3 w-fit"
          >
            <ArrowLeft size={12} />
            대시보드로 돌아가기
          </button>
          <h1 className="text-xl font-bold font-mono text-foreground">프로토타입 결과 비교</h1>
          <p className="text-xs text-muted-foreground mt-1">{completedSessions.length}개 프로토타입의 실험 결과를 비교합니다</p>
        </div>
      </div>

      {/* Chart Section */}
      <div className="px-8 py-6">
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mb-6">
          {sessionResults.map((result) => {
            const archColor = ARCHITECTURE_COLORS[result.session.architecture] || ARCHITECTURE_COLORS.CrewAI;
            return (
              <div key={`profile-${result.session.run_id}`} className="rounded-xl border border-border/50 bg-card p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <span
                      className="inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold font-mono uppercase tracking-wider"
                      style={{ color: archColor.text, backgroundColor: archColor.bg }}
                    >
                      {result.session.architecture}
                    </span>
                    <h3 className="mt-2 text-sm font-semibold font-mono text-foreground">{result.profile.label}</h3>
                    <p className="mt-1 text-xs text-muted-foreground">{result.profile.tagline}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Execution model</p>
                    <p className="mt-1 text-xs font-semibold" style={{ color: archColor.text }}>
                      {result.profile.executionModel}
                    </p>
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap gap-1.5">
                  {result.signature.map((item) => (
                    <span key={item} className="rounded-full px-2 py-1 text-[10px] font-mono" style={{ color: archColor.text, backgroundColor: archColor.bg }}>
                      {item}
                    </span>
                  ))}
                </div>

                <div className="mt-4 grid grid-cols-2 gap-2">
                  <div className="rounded-lg border border-border/30 bg-background/50 px-3 py-2">
                    <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Turns</p>
                    <p className="mt-1 text-sm font-semibold font-mono text-foreground">{result.analytics.agentTurns}</p>
                  </div>
                  <div className="rounded-lg border border-border/30 bg-background/50 px-3 py-2">
                    <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Tools</p>
                    <p className="mt-1 text-sm font-semibold font-mono text-foreground">{result.analytics.toolCalls}</p>
                  </div>
                  <div className="rounded-lg border border-border/30 bg-background/50 px-3 py-2">
                    <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Transitions</p>
                    <p className="mt-1 text-sm font-semibold font-mono text-foreground">
                      {Math.max(result.analytics.phaseCount, result.analytics.handoffs, 1)}
                    </p>
                  </div>
                  <div className="rounded-lg border border-border/30 bg-background/50 px-3 py-2">
                    <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Blockers</p>
                    <p className="mt-1 text-sm font-semibold font-mono text-foreground">{result.analytics.blockerCount}</p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="rounded-xl border border-border/50 bg-card overflow-hidden mb-6">
          <div className="px-4 py-3 border-b border-border/30 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <TrendingUp size={14} className="text-[#2563EB]" />
              <h3 className="text-sm font-semibold font-mono text-foreground">메트릭 시각화</h3>
            </div>
            <div className="flex items-center gap-1 bg-muted/30 rounded-md p-0.5">
              <button
                onClick={() => setChartMode('bar')}
                className={`text-[10px] font-mono px-2 py-1 rounded transition-colors ${
                  chartMode === 'bar' ? 'bg-[#2563EB]/20 text-[#2563EB]' : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                바 차트
              </button>
              <button
                onClick={() => setChartMode('radar')}
                className={`text-[10px] font-mono px-2 py-1 rounded transition-colors ${
                  chartMode === 'radar' ? 'bg-[#2563EB]/20 text-[#2563EB]' : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                레이더
              </button>
            </div>
          </div>
          <div className="p-4">
            {chartMode === 'bar' ? (
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis
                    dataKey="metric"
                    tick={{ fill: '#9CA3AF', fontSize: 10, fontFamily: 'JetBrains Mono' }}
                    stroke="rgba(255,255,255,0.1)"
                  />
                  <YAxis
                    tick={{ fill: '#9CA3AF', fontSize: 10, fontFamily: 'JetBrains Mono' }}
                    stroke="rgba(255,255,255,0.1)"
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1a1f2e',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: '8px',
                      fontSize: '11px',
                      fontFamily: 'JetBrains Mono',
                    }}
                    labelStyle={{ color: '#9CA3AF' }}
                  />
                  <Legend
                    wrapperStyle={{ fontSize: '10px', fontFamily: 'JetBrains Mono' }}
                  />
                  {sessionResults.map((r, i) => (
                    <Bar
                      key={r.session.architecture}
                      dataKey={r.session.architecture}
                      fill={archColors[i]}
                      fillOpacity={0.8}
                      radius={[4, 4, 0, 0]}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <ResponsiveContainer width="100%" height={320}>
                <RadarChart data={radarData}>
                  <PolarGrid stroke="rgba(255,255,255,0.1)" />
                  <PolarAngleAxis
                    dataKey="metric"
                    tick={{ fill: '#9CA3AF', fontSize: 9, fontFamily: 'JetBrains Mono' }}
                  />
                  <PolarRadiusAxis
                    angle={30}
                    domain={[0, 100]}
                    tick={{ fill: '#555', fontSize: 8 }}
                    stroke="rgba(255,255,255,0.05)"
                  />
                  {sessionResults.map((r, i) => (
                    <Radar
                      key={r.session.architecture}
                      name={r.session.architecture}
                      dataKey={r.session.architecture}
                      stroke={archColors[i]}
                      fill={archColors[i]}
                      fillOpacity={0.15}
                      strokeWidth={2}
                    />
                  ))}
                  <Legend wrapperStyle={{ fontSize: '10px', fontFamily: 'JetBrains Mono' }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1a1f2e',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: '8px',
                      fontSize: '11px',
                      fontFamily: 'JetBrains Mono',
                    }}
                  />
                </RadarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* Architecture Cards */}
        <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${sessionResults.length}, 1fr)` }}>
          {sessionResults.map((result, index) => {
            const archColor = ARCHITECTURE_COLORS[result.session.architecture] || ARCHITECTURE_COLORS.CrewAI;
            return (
              <motion.div
                key={result.session.run_id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: index * 0.1 }}
                className="rounded-xl border border-border/50 bg-card overflow-hidden"
              >
                <div className="px-4 py-3 border-b border-border/30" style={{ backgroundColor: archColor.bg }}>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold font-mono uppercase tracking-wider" style={{ color: archColor.text }}>
                      {result.session.architecture}
                    </span>
                    <span className="text-[10px] font-mono text-muted-foreground">{result.resultCount}개 실험</span>
                  </div>
                  <p className="text-xs text-foreground/70 mt-1 line-clamp-1">{result.session.research_topic}</p>
                </div>
                <div className="p-4 space-y-3">
                  {allMetricKeys.map(key => {
                    const value = result.metrics[key];
                    const isBest = bestMetrics[key]?.runId === result.session.run_id;
                    const formattedValue = value !== undefined
                      ? (value < 1 && value > 0 ? `${(value * 100).toFixed(2)}%` : value.toFixed(2))
                      : 'N/A';
                    return (
                      <div key={key} className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <MetricIcon metricKey={key} />
                          <span className="text-[10px] font-mono text-muted-foreground uppercase">{key.replace(/_/g, ' ')}</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className={`text-sm font-semibold font-mono ${isBest ? 'text-[#2563EB]' : 'text-foreground/70'}`}>
                            {formattedValue}
                          </span>
                          {isBest && <Trophy size={10} className="text-amber-400" />}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </motion.div>
            );
          })}
        </div>

        {/* Summary Table */}
        {allMetricKeys.length > 0 && (
          <div className="mt-6 rounded-xl border border-border/50 bg-card overflow-hidden">
            <div className="px-4 py-3 border-b border-border/30">
              <h3 className="text-sm font-semibold font-mono text-foreground">종합 비교 테이블</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-border/30">
                    <th className="text-left px-4 py-2 text-[10px] font-mono text-muted-foreground uppercase tracking-wider">메트릭</th>
                    {sessionResults.map(r => (
                      <th
                        key={r.session.run_id}
                        className="text-right px-4 py-2 text-[10px] font-mono uppercase tracking-wider"
                        style={{ color: ARCHITECTURE_COLORS[r.session.architecture]?.text }}
                      >
                        {r.session.architecture}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {allMetricKeys.map(key => (
                    <tr key={key} className="border-b border-border/20 last:border-0">
                      <td className="px-4 py-2.5 text-xs font-mono text-muted-foreground">{key.replace(/_/g, ' ')}</td>
                      {sessionResults.map(r => {
                        const value = r.metrics[key];
                        const isBest = bestMetrics[key]?.runId === r.session.run_id;
                        return (
                          <td key={r.session.run_id} className="text-right px-4 py-2.5">
                            <span className={`text-xs font-mono ${isBest ? 'text-[#2563EB] font-semibold' : 'text-foreground/60'}`}>
                              {value !== undefined
                                ? (value < 1 && value > 0 ? `${(value * 100).toFixed(2)}%` : value.toFixed(2))
                                : '-'}
                            </span>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function MetricIcon({ metricKey }: { metricKey: string }) {
  const iconProps = { size: 10, className: 'text-muted-foreground/60' };
  if (metricKey.includes('accuracy')) return <BarChart3 {...iconProps} />;
  if (metricKey.includes('time')) return <Clock {...iconProps} />;
  if (metricKey.includes('memory')) return <HardDrive {...iconProps} />;
  if (metricKey.includes('loss')) return <BarChart3 {...iconProps} />;
  return <Cpu {...iconProps} />;
}
