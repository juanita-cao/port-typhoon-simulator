import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Spin, Alert, Button, Slider, Row, Col, Typography } from 'antd'
import { PlayCircleOutlined, BarChartOutlined } from '@ant-design/icons'
import { api } from './api/api'
import type { ScenarioRow, SimResultsResponse } from './api/types'
import PortAnimation from './components/PortAnimation'
import HeatmapChart from './components/HeatmapChart'
import RunMetaCard from './components/RunMetaCard'
import ScenarioTable from './components/ScenarioTable'

const { Text } = Typography

type Mode = 'instant' | 'live'

export default function App() {
  const [mode, setMode]                   = useState<Mode>('instant')
  const [nReps, setNReps]                 = useState(20)
  const [selectedScenario, setSelectedScenario] = useState<ScenarioRow | null>(null)
  const [liveData, setLiveData]           = useState<SimResultsResponse | null>(null)

  const { data: precomputed, isLoading, error } = useQuery({
    queryKey: ['results'],
    queryFn:  api.getResults,
  })

  const simulate = useMutation({
    mutationFn: () => api.simulate({ n_replications: nReps }),
    onSuccess:  (data) => setLiveData(data),
  })

  const data      = mode === 'live' && liveData ? liveData : precomputed
  const isRunning = simulate.isPending

  // default: Cat5 · 0–100 km (scenario_id = 21)
  const activeScenario = selectedScenario
    ?? data?.scenarios.find(s => s.scenario_id === 21)
    ?? data?.scenarios[0]
    ?? null

  return (
    <div style={{ minHeight: '100vh', background: '#040810', padding: '14px' }}>

      {/* ── Header ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 12,
        paddingBottom: 10,
        borderBottom: '1px solid #0e1e2e',
      }}>
        <div>
          <div style={{ color: '#94a3b8', fontSize: 18, fontWeight: 600, letterSpacing: 0.3 }}>
            Port Disruption Impact Simulator
          </div>
        </div>

        {/* Mode toggle — custom buttons (avoids Ant Design Segmented dark-theme issues) */}
        <div style={{
          display: 'flex',
          background: '#0a1525',
          borderRadius: 6,
          padding: 3,
          border: '1px solid #1a2e42',
          gap: 2,
        }}>
          {([
            { id: 'instant' as Mode, icon: <BarChartOutlined />, label: 'INSTANT RESULTS' },
            { id: 'live'    as Mode, icon: <PlayCircleOutlined />, label: 'LIVE SIMULATION' },
          ]).map(({ id, icon, label }) => (
            <button
              key={id}
              onClick={() => setMode(id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '6px 16px',
                borderRadius: 4, border: 'none', cursor: 'pointer',
                background: mode === id ? '#1e3a5c' : 'transparent',
                color:      mode === id ? '#38bdf8' : '#334155',
                fontSize:   11,
                fontFamily: 'monospace',
                letterSpacing: 0.8,
                fontWeight: mode === id ? 700 : 400,
                transition: 'all 0.15s',
                outline:    mode === id ? '1px solid #1e4a70' : 'none',
              }}
            >
              {icon} {label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Port Animation ── */}
      <div style={{ marginBottom: 14 }}>
        <PortAnimation
          scenario={activeScenario}
          numBerths={data?.port_anim.num_berths ?? 16}
          meanInterarrivalHrs={data?.port_anim.mean_interarrival_hrs ?? 47.04}
          isRunning={isRunning}
          mode={mode}
        />
      </div>

      {/* ── Loading / error ── */}
      {isLoading && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin size="large" />
        </div>
      )}
      {error && (
        <Alert type="error" message="Failed to load pre-computed results"
          description="Start the backend: cd src && uvicorn backend.main:app --port 8000" />
      )}

      {/* ── Results area ── */}
      {data && (
        <Row gutter={14}>

          {/* Left: Run metadata + controls */}
          <Col xs={24} lg={5}>
            <RunMetaCard
              metadata={data.run_metadata}
              intactTeu={data.intact_throughput_mean_teu}
              nReplications={data.n_replications}
            />
            {mode === 'live' && (
              <div style={{ marginTop: 10, padding: 12,
                background: '#0a1525', borderRadius: 8, border: '1px solid #1a2e42' }}>
                <Text style={{ color: '#475569', display: 'block', marginBottom: 8,
                  fontSize: 11, fontFamily: 'monospace', letterSpacing: 0.5 }}>
                  REPLICATIONS (QUICK MODE)
                </Text>
                <Slider min={10} max={50} step={10} value={nReps}
                  onChange={setNReps}
                  marks={{ 10: '10', 20: '20', 30: '30', 50: '50' }} />
                <Button
                  type="primary" block
                  style={{ marginTop: 14, background: mode === 'live' ? '#1e3a5c' : undefined,
                    borderColor: '#1e4a70', fontFamily: 'monospace', letterSpacing: 0.5 }}
                  icon={<PlayCircleOutlined />}
                  loading={isRunning}
                  onClick={() => simulate.mutate()}
                >
                  {isRunning ? `RUNNING ${nReps} REPS…` : `RUN SIMULATION (${nReps} REPS)`}
                </Button>
                {simulate.isError && (
                  <Alert type="error" message="Simulation failed" style={{ marginTop: 8 }} />
                )}
              </div>
            )}
          </Col>

          {/* Center: Heatmap */}
          <Col xs={24} lg={11}>
            <HeatmapChart
              scenarios={data.scenarios}
              selectedId={activeScenario?.scenario_id ?? null}
              onSelect={setSelectedScenario}
            />
          </Col>

          {/* Right: Scenario list */}
          <Col xs={24} lg={8}>
            <ScenarioTable
              scenarios={data.scenarios}
              selectedId={activeScenario?.scenario_id ?? null}
              onSelect={setSelectedScenario}
            />
          </Col>
        </Row>
      )}

      {/* ── Footer ── */}
      <div style={{
        marginTop: 24, paddingTop: 12,
        borderTop: '1px solid #0e1e2e',
        display: 'flex', justifyContent: 'center',
      }}>
        <Text style={{ color: '#1e3a55', fontSize: 10, fontFamily: 'monospace', letterSpacing: 1 }}>
          Powered by InnerDrive Studio · © {new Date().getFullYear()} All Rights Reserved
        </Text>
      </div>
    </div>
  )
}
