import { Tag, Typography } from 'antd'
import type { ScenarioRow } from '../api/types'

const { Text } = Typography

const SIGNAL_TAG: Record<string, { color: string; label: string }> = {
  DIFFERENT_AND_MEANINGFUL:                   { color: 'red',    label: 'Meaningful' },
  STAT_SIGNIFICANT_BUT_PRACTICALLY_NEGLIGIBLE:{ color: 'orange', label: 'Stat-sig' },
  NOT_SIGNIFICANT:                             { color: 'default',label: 'NS' },
}

interface Props {
  scenarios: ScenarioRow[]
  selectedId: number | null
  onSelect: (s: ScenarioRow) => void
}

export default function ScenarioTable({ scenarios, selectedId, onSelect }: Props) {
  return (
    <div style={{ background: '#0f1729', borderRadius: 12,
      border: '1px solid #1e293b', padding: 12, height: '100%' }}>

      <Text style={{ color: '#94a3b8', fontSize: 12, display: 'block', marginBottom: 8 }}>
        All 25 Scenarios · Holm-Bonferroni corrected
      </Text>

      {/* header */}
      <div style={{ display: 'grid', gridTemplateColumns: '44px 72px 60px 56px 80px',
        gap: 4, paddingBottom: 6, borderBottom: '1px solid #1e293b', marginBottom: 4 }}>
        {['Scen', 'Cat·Dist', 'Loss%', 'dz', 'Signal'].map(h => (
          <Text key={h} style={{ color: '#475569', fontSize: 10 }}>{h}</Text>
        ))}
      </div>

      {/* rows */}
      <div style={{ maxHeight: 340, overflowY: 'auto' }}>
        {scenarios.map(s => {
          const isSelected = s.scenario_id === selectedId
          const sig = SIGNAL_TAG[s.decision_signal]
          return (
            <div key={s.scenario_id}
              onClick={() => onSelect(s)}
              style={{
                display: 'grid',
                gridTemplateColumns: '44px 72px 60px 56px 80px',
                gap: 4, padding: '5px 4px', cursor: 'pointer', borderRadius: 6,
                background: isSelected ? '#1e1b4b' : 'transparent',
                border: `1px solid ${isSelected ? '#7c3aed' : 'transparent'}`,
                marginBottom: 2, transition: 'all 0.12s',
              }}>
              <Text style={{ color: '#64748b', fontSize: 11 }}>#{s.scenario_id}</Text>
              <Text style={{ color: '#94a3b8', fontSize: 11 }}>
                C{s.typhoon_cat}·{s.dist_range_km.replace(' km','').replace('–','‑')}
              </Text>
              <Text style={{
                color: s.decreased_pct > 10 ? '#f87171' : s.decreased_pct > 3 ? '#fbbf24' : '#64748b',
                fontSize: 11, fontWeight: s.operationally_meaningful ? 700 : 400,
              }}>
                {s.decreased_pct.toFixed(1)}%
              </Text>
              <Text style={{ color: '#64748b', fontSize: 11 }}>
                {s.dz.toFixed(2)}
              </Text>
              <Tag color={sig.color} style={{ fontSize: 9, padding: '0 4px',
                lineHeight: '16px', margin: 0 }}>
                {sig.label}
              </Tag>
            </div>
          )
        })}
      </div>

      {/* summary */}
      <div style={{ borderTop: '1px solid #1e293b', marginTop: 8, paddingTop: 8 }}>
        <Text style={{ color: '#64748b', fontSize: 11 }}>
          Meaningful: <Text style={{ color: '#ef4444', fontWeight: 700 }}>
            {scenarios.filter(s => s.operationally_meaningful).length}
          </Text> / 25
          {'  ·  '}
          Holm-sig: <Text style={{ color: '#f59e0b', fontWeight: 700 }}>
            {scenarios.filter(s => s.is_significant_holm).length}
          </Text> / 25
        </Text>
      </div>
    </div>
  )
}
