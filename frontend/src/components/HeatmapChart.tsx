/**
 * HeatmapChart — 5×5 scenario grid (typhoon category × distance bin)
 * Click a cell → highlights that scenario in animation + table
 */
import { Typography, Tooltip } from 'antd'
import type { ScenarioRow } from '../api/types'

const { Text } = Typography

const SIGNAL_BORDER: Record<string, string> = {
  DIFFERENT_AND_MEANINGFUL: '#ef4444',
  STAT_SIGNIFICANT_BUT_PRACTICALLY_NEGLIGIBLE: '#f59e0b',
  NOT_SIGNIFICANT: '#334155',
}

const DIST_LABELS = ['0–100 km', '101–200 km', '201–300 km', '301–400 km', '401–500 km']

interface Props {
  scenarios: ScenarioRow[]
  selectedId: number | null
  onSelect: (s: ScenarioRow) => void
}

export default function HeatmapChart({ scenarios, selectedId, onSelect }: Props) {
  const cell = (cat: number, bin: number) =>
    scenarios.find(s => s.typhoon_cat === cat && s.dist_bin === bin)

  return (
    <div style={{ background: '#0f1729', borderRadius: 12,
      border: '1px solid #1e293b', padding: 16 }}>
      <Text style={{ color: '#94a3b8', fontSize: 12, display: 'block', marginBottom: 12 }}>
        Throughput Loss (%) · click cell to animate
      </Text>

      {/* Column headers */}
      <div style={{ display: 'grid', gridTemplateColumns: '64px repeat(5, 1fr)',
        gap: 4, marginBottom: 4 }}>
        <div />
        {DIST_LABELS.map(l => (
          <Text key={l} style={{ color: '#475569', fontSize: 10,
            textAlign: 'center', display: 'block' }}>{l}</Text>
        ))}
      </div>

      {/* Rows: Cat 1–5 */}
      {[1, 2, 3, 4, 5].map(cat => (
        <div key={cat} style={{ display: 'grid',
          gridTemplateColumns: '64px repeat(5, 1fr)', gap: 4, marginBottom: 4 }}>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <Text style={{ color: '#64748b', fontSize: 11 }}>Cat {cat}</Text>
          </div>
          {[1, 2, 3, 4, 5].map(bin => {
            const s = cell(cat, bin)
            if (!s) return <div key={bin} />
            const isSelected = s.scenario_id === selectedId
            const pct = s.decreased_pct
            // color intensity 0–100% → opacity
            const intensity = Math.min(pct / 40, 1)
            const bg = s.decision_signal === 'DIFFERENT_AND_MEANINGFUL'
              ? `rgba(239,68,68,${0.15 + intensity * 0.6})`
              : s.decision_signal === 'STAT_SIGNIFICANT_BUT_PRACTICALLY_NEGLIGIBLE'
                ? `rgba(245,158,11,${0.15 + intensity * 0.4})`
                : `rgba(30,41,59,${0.5 + intensity * 0.3})`

            return (
              <Tooltip key={bin} title={
                <div style={{ fontSize: 12 }}>
                  <div><b>Scenario {s.scenario_id}</b> · Cat {s.typhoon_cat} · {s.dist_range_km}</div>
                  <div>Loss: {pct.toFixed(1)}% · dz={s.dz.toFixed(2)}</div>
                  <div>p={s.p_value.toFixed(3)} · {s.decision_signal.replace(/_/g, ' ')}</div>
                  <div>Disruption: {s.disruption_days_mean.toFixed(1)} days avg</div>
                </div>
              }>
                <div
                  onClick={() => onSelect(s)}
                  style={{
                    background: bg,
                    border: `2px solid ${isSelected ? '#a78bfa' : SIGNAL_BORDER[s.decision_signal]}`,
                    borderRadius: 6, padding: '6px 4px',
                    cursor: 'pointer', textAlign: 'center',
                    transition: 'all 0.15s',
                    transform: isSelected ? 'scale(1.05)' : 'scale(1)',
                    boxShadow: isSelected ? '0 0 0 2px #7c3aed' : 'none',
                  }}>
                  <Text style={{
                    color: pct > 10 ? '#fca5a5' : pct > 3 ? '#fcd34d' : '#64748b',
                    fontSize: 13, fontWeight: 700, display: 'block',
                  }}>
                    {pct.toFixed(1)}%
                  </Text>
                  {s.operationally_meaningful && (
                    <Text style={{ color: '#ef4444', fontSize: 8 }}>●</Text>
                  )}
                </div>
              </Tooltip>
            )
          })}
        </div>
      ))}

      {/* Legend */}
      <div style={{ display: 'flex', gap: 12, marginTop: 12, flexWrap: 'wrap' }}>
        {[
          { color: '#ef4444', label: '● Meaningful impact' },
          { color: '#f59e0b', label: '◐ Stat-sig only' },
          { color: '#475569', label: '○ Not significant' },
        ].map(({ color, label }) => (
          <Text key={label} style={{ color, fontSize: 11 }}>{label}</Text>
        ))}
      </div>
    </div>
  )
}
