/**
 * PortAnimation — top-down SVG digital twin port diagram
 *
 * Zones (800×340 viewBox):
 *   y 0–115    = Sea / Approach Channel — ships arrive from right
 *   y 115–128  = Quay Wall (wharf structure)
 *   y 128–220  = Terminal — 16 berths in single row along quay
 *   y 220–340  = Staging / Anchorage Queue
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import type { ScenarioRow } from '../api/types'

// ── Layout ────────────────────────────────────────────────────────────────────
const W         = 800
const H         = 340
const SEA_H     = 115
const QUAY_Y    = SEA_H          // 115
const QUAY_H    = 13
const PORT_Y    = QUAY_Y + QUAY_H  // 128
const PORT_H    = 92
const QUEUE_Y   = PORT_Y + PORT_H  // 220

// ── Berths: 16 in single row along quay ──────────────────────────────────────
const NUM_BERTHS     = 16
const BERTH_W        = 40
const BERTH_H        = 60
const BERTH_PAD      = 5
const BERTHS_TOTAL_W = NUM_BERTHS * (BERTH_W + BERTH_PAD) - BERTH_PAD  // 715
const BERTHS_START_X = Math.round((W - BERTHS_TOTAL_W) / 2)             // 42

// ── Ship dimensions ───────────────────────────────────────────────────────────
const SHIP_W  = 26
const SHIP_H  = 11
const SPAWN_X = W + 40
const QUEUE_X = 50   // anchorage left anchor

// ── Types ─────────────────────────────────────────────────────────────────────
type ShipStatus   = 'arriving' | 'queued' | 'berthing' | 'in_berth' | 'departing'
type TyphoonPhase = 'none' | 'warning' | 'impact' | 'recovery'

interface Ship {
  id:         number
  x:          number
  y:          number
  berthIndex: number
  status:     ShipStatus
  color:      string
}

interface TyphoonState {
  phase:    TyphoonPhase
  x:        number
  y:        number
  scale:    number
  rotation: number
}

interface PortState {
  berths:          boolean[]
  ships:           Ship[]
  queueLength:     number
  throughputCount: number
  typhoon:         TyphoonState
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function berthPosition(idx: number): { x: number; y: number } {
  return {
    x: BERTHS_START_X + idx * (BERTH_W + BERTH_PAD) + BERTH_W / 2,
    y: PORT_Y + BERTH_H / 2 + 4,   // near quay face
  }
}

const VESSEL_COLORS = ['#0ea5e9', '#22d3ee', '#38bdf8', '#67e8f9', '#06b6d4', '#7dd3fc']
function randomColor() {
  return VESSEL_COLORS[Math.floor(Math.random() * VESSEL_COLORS.length)]
}

// ── Component ─────────────────────────────────────────────────────────────────
interface Props {
  scenario:            ScenarioRow | null
  numBerths:           number
  meanInterarrivalHrs: number
  isRunning:           boolean
  mode:                'instant' | 'live'
}

export default function PortAnimation({ scenario, numBerths, isRunning: _isRunning, mode }: Props) {
  const nextId       = useRef(0)
  const frameRef     = useRef<number | undefined>(undefined)
  const lastSpawnRef = useRef(0)
  const [, setAnimTick] = useState(0)

  const stateRef = useRef<PortState>({
    berths:          Array(numBerths).fill(false),
    ships:           [],
    queueLength:     0,
    throughputCount: 0,
    typhoon:         { phase: 'none', x: W - 75, y: 32, scale: 0, rotation: 0 },
  })

  const typhoonCat     = scenario?.typhoon_cat        ?? 5
  const disruptionDays = scenario?.disruption_days_mean ?? 30
  // 15–35 s closure for clear demo visibility
  const closureSecs = 15 + Math.min(disruptionDays / 60, 1) * 20

  const closureRef  = useRef({ active: false, endTime: 0, warningTime: 0 })
  const lastTimeRef = useRef<number>(0)

  const scheduleTyphoon = useCallback(() => {
    closureRef.current.warningTime = performance.now() + (mode === 'instant' ? 15000 : 20000)
    closureRef.current.endTime     = 0
    closureRef.current.active      = false
  }, [mode])

  useEffect(() => { scheduleTyphoon() }, [scheduleTyphoon])

  useEffect(() => {
    const s = stateRef.current
    s.typhoon = { phase: 'none', x: W - 75, y: 32, scale: 0, rotation: 0 }
    closureRef.current = { active: false, endTime: 0, warningTime: 0 }
    scheduleTyphoon()
  }, [scenario?.scenario_id, scheduleTyphoon])

  // ── Main animation loop ───────────────────────────────────────────────────
  useEffect(() => {
    const SPAWN_INTERVAL_MS = 2200
    const MOVE_SPEED        = 1.8

    function tick(now: number) {
      const dt      = now - (lastTimeRef.current || now)
      lastTimeRef.current = now
      const s       = stateRef.current
      const closure = closureRef.current

      // ── Typhoon phases ──
      const t = s.typhoon
      t.rotation -= dt * 0.15

      if (t.phase === 'none' && closure.warningTime > 0 && now >= closure.warningTime) {
        t.phase = 'warning'; t.x = W - 80; t.y = 28; t.scale = 0.3
        closure.warningTime = 0
      }

      if (t.phase === 'warning') {
        t.scale = Math.min(1.0, t.scale + dt * 0.00025)   // ~2.8s warning phase
        if (t.scale >= 1.0) {
          t.phase = 'impact'
          closure.active  = true
          closure.endTime = now + closureSecs * 1000
        }
      }

      if (t.phase === 'impact') {
        t.x     = Math.max(W / 2 - 60, t.x - dt * 0.012)   // slow drift across sea
        t.scale = 1.4 + typhoonCat * 0.12
        if (now >= closure.endTime) { t.phase = 'recovery'; closure.active = false }
      }

      if (t.phase === 'recovery') {
        t.x    -= dt * 0.022
        t.scale = Math.max(0, t.scale - dt * 0.00022)       // ~7s dissipation for cat5
        if (t.scale <= 0) {
          t.phase = 'none'
          closure.warningTime = now + (mode === 'instant' ? 20000 : 40000)
        }
      }

      const portClosed = closure.active

      // ── Spawn ──
      if (now - lastSpawnRef.current > SPAWN_INTERVAL_MS) {
        lastSpawnRef.current = now
        s.ships.push({
          id: nextId.current++, x: SPAWN_X,
          y: 30 + Math.random() * 55,
          berthIndex: -1, status: 'arriving', color: randomColor(),
        })
      }

      // ── Complete service ──
      if (!portClosed) {
        for (const sh of s.ships.filter(sh => sh.status === 'in_berth')) {
          if (Math.random() < 0.003 * (dt / 16)) {
            sh.status = 'departing'
            s.berths[sh.berthIndex] = false
            s.throughputCount++
          }
        }
      }

      // ── Move ships ──
      const nextShips: Ship[] = []
      for (const sh of s.ships) {
        switch (sh.status) {
          case 'arriving': {
            sh.x -= MOVE_SPEED * (dt / 16)
            const qLen    = s.ships.filter(x => x.status === 'queued').length
            const targetX = QUEUE_X + qLen * (SHIP_W + 6)
            if (sh.x <= targetX + 80) {
              sh.status = 'queued'
              s.queueLength = Math.max(0, s.queueLength + 1)
            }
            nextShips.push(sh)
            break
          }
          case 'queued': {
            if (!portClosed) {
              const free = s.berths.findIndex(b => !b)
              if (free !== -1) {
                s.berths[free] = true; sh.berthIndex = free
                sh.status = 'berthing'; s.queueLength = Math.max(0, s.queueLength - 1)
              }
            }
            nextShips.push(sh)
            break
          }
          case 'berthing': {
            const tgt  = berthPosition(sh.berthIndex)
            const dx   = tgt.x - sh.x
            const dy   = tgt.y - sh.y
            const dist = Math.sqrt(dx * dx + dy * dy)
            if (dist < 3) {
              sh.x = tgt.x; sh.y = tgt.y; sh.status = 'in_berth'
            } else {
              sh.x += (dx / dist) * MOVE_SPEED * 1.2 * (dt / 16)
              sh.y += (dy / dist) * MOVE_SPEED * 1.2 * (dt / 16)
            }
            nextShips.push(sh)
            break
          }
          case 'in_berth': { nextShips.push(sh); break }
          case 'departing': {
            sh.x -= MOVE_SPEED * 1.5 * (dt / 16)   // depart left (back to open sea)
            sh.y += (SEA_H / 2 - sh.y) * 0.04 * (dt / 16)
            if (sh.x > -40) nextShips.push(sh)
            break
          }
        }
      }

      s.ships = nextShips.slice(-80)
      setAnimTick(n => n + 1)
      frameRef.current = requestAnimationFrame(tick)
    }

    frameRef.current = requestAnimationFrame(tick)
    return () => { if (frameRef.current) cancelAnimationFrame(frameRef.current) }
  }, [closureSecs, typhoonCat, mode])

  // ── Render ────────────────────────────────────────────────────────────────
  const s          = stateRef.current
  const t          = s.typhoon
  const portClosed = closureRef.current.active
  const occupied   = s.berths.filter(Boolean).length

  return (
    <div style={{ background: '#060d1a', borderRadius: 8, overflow: 'hidden',
      border: '1px solid #0e1e30' }}>

      {/* ── HMI status header ── */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '5px 14px', background: '#07101c',
        borderBottom: '1px solid #0e1e30',
      }}>
        <span style={{ color: '#1e3a55', fontSize: 9.5, letterSpacing: 2.5, fontFamily: 'monospace' }}>
          DT-SIM · PORT DIGITAL TWIN
        </span>
        <div style={{ display: 'flex', gap: 22, alignItems: 'center' }}>
          <HmiStat label="VESSELS SERVED" value={String(s.throughputCount)} color="#38bdf8" />
          <HmiStat label="AT BERTH" value={`${occupied}/${numBerths}`} color="#22c55e" />
          <HmiStat label="QUEUE" value={String(s.queueLength)}
            color={s.queueLength > 5 ? '#f87171' : '#334155'} />
          <HmiStat
            label="SCENARIO"
            value={scenario ? `CAT ${scenario.typhoon_cat} · ${scenario.dist_range_km}` : '—'}
            color="#a78bfa" />
          {portClosed && (
            <span style={{
              color: '#ef4444', fontSize: 9, fontWeight: 700, letterSpacing: 2,
              fontFamily: 'monospace', padding: '2px 8px',
              border: '1px solid #5a1010', borderRadius: 2,
            }}>SUSPENDED</span>
          )}
        </div>
      </div>

      {/* ── SVG canvas ── */}
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block' }}>
        <defs>
          <linearGradient id="dt-sea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={portClosed ? '#130404' : '#030d1d'} />
            <stop offset="100%" stopColor={portClosed ? '#1f0606' : '#061525'} />
          </linearGradient>
          <linearGradient id="dt-port" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#070e1a" />
            <stop offset="100%" stopColor="#04080f" />
          </linearGradient>
        </defs>

        {/* ── Sea / Approach Channel ── */}
        <rect x={0} y={0} width={W} height={SEA_H} fill="url(#dt-sea)" />

        {/* Nautical grid */}
        {[29, 57, 86].map(y => (
          <line key={`gh${y}`} x1={0} y1={y} x2={W} y2={y}
            stroke="rgba(0,130,220,0.04)" strokeWidth={1} />
        ))}
        {[100, 200, 300, 400, 500, 600, 700].map(x => (
          <line key={`gv${x}`} x1={x} y1={0} x2={x} y2={SEA_H}
            stroke="rgba(0,130,220,0.03)" strokeWidth={1} />
        ))}

        {/* Approach channel centerline */}
        <line x1={0} y1={SEA_H / 2} x2={W} y2={SEA_H / 2}
          stroke="rgba(0,100,160,0.1)" strokeWidth={1} strokeDasharray="18 10" />

        <text x={14} y={13} fill="rgba(56,189,248,0.15)"
          fontSize={8} letterSpacing={3.5} fontFamily="monospace">APPROACH CHANNEL</text>

        <text x={W - 14} y={SEA_H / 2 + 4} textAnchor="end"
          fill="rgba(56,189,248,0.3)" fontSize={11}>←</text>
        <text x={W - 16} y={SEA_H / 2 - 5} textAnchor="end"
          fill="rgba(56,189,248,0.18)" fontSize={8} fontFamily="monospace">INBOUND</text>

        {/* ── Quay Wall ── */}
        <rect x={0} y={QUAY_Y} width={W} height={QUAY_H}
          fill={portClosed ? '#190505' : '#080f1c'} />
        <line x1={0} y1={QUAY_Y} x2={W} y2={QUAY_Y}
          stroke={portClosed ? '#6b1010' : '#0c3044'} strokeWidth={2} />
        <line x1={0} y1={QUAY_Y + QUAY_H} x2={W} y2={QUAY_Y + QUAY_H}
          stroke={portClosed ? '#3a0c0c' : '#07202e'} strokeWidth={1} />

        {/* Quay tick marks */}
        {Array.from({ length: 24 }, (_, i) => (
          <line key={`qt${i}`}
            x1={BERTHS_START_X + i * (715 / 23)} y1={QUAY_Y}
            x2={BERTHS_START_X + i * (715 / 23)} y2={QUAY_Y + 5}
            stroke={portClosed ? '#2e0a0a' : '#0a2030'} strokeWidth={1} />
        ))}

        {/* Quay status label */}
        <text x={14} y={QUAY_Y + 9}
          fill={portClosed ? '#4a0e0e' : '#0c2a38'}
          fontSize={7.5} letterSpacing={1.5} fontFamily="monospace" fontWeight="700">
          {portClosed
            ? 'QUAY — OPERATIONS SUSPENDED · TYPHOON CLOSURE IN EFFECT'
            : 'QUAY — OPERATIONAL'}
        </text>

        {/* ── Terminal / Berths ── */}
        <rect x={0} y={PORT_Y} width={W} height={PORT_H} fill="url(#dt-port)" />

        {portClosed && (
          <rect x={0} y={PORT_Y} width={W} height={PORT_H} fill="rgba(90,12,8,0.09)" />
        )}

        {/* 16 berths in single row */}
        {s.berths.map((occ, i) => {
          const bx        = BERTHS_START_X + i * (BERTH_W + BERTH_PAD)
          const by        = PORT_Y + 2
          const disrupted = occ && portClosed

          // Color scheme: clearly distinct empty / occupied / disrupted
          const fill   = disrupted ? '#1e0606' : occ ? '#071a0d' : '#0e1e35'
          const stroke = disrupted ? '#a01818' : occ ? '#1a7a30' : '#2a5080'
          const dotFill= disrupted ? '#ef4444' : occ ? '#22c55e' : '#2a4a70'
          const labelC = disrupted ? '#c04040' : occ ? '#22c55e' : '#3a6090'

          return (
            <g key={i}>
              {/* Berth slot */}
              <rect x={bx} y={by} width={BERTH_W} height={BERTH_H} rx={1}
                fill={fill} stroke={stroke} strokeWidth={1.5} />

              {/* Quay face — thick top edge */}
              <line x1={bx} y1={by} x2={bx + BERTH_W} y2={by}
                stroke={disrupted ? '#c02020' : occ ? '#1a9a30' : '#2e6090'}
                strokeWidth={3} />

              {/* Fender lines (vertical dock guides on each side) */}
              <line x1={bx + 3} y1={by + 4} x2={bx + 3} y2={by + BERTH_H - 4}
                stroke={stroke} strokeWidth={0.8} opacity={0.5} />
              <line x1={bx + BERTH_W - 3} y1={by + 4} x2={bx + BERTH_W - 3} y2={by + BERTH_H - 4}
                stroke={stroke} strokeWidth={0.8} opacity={0.5} />

              {/* Status dot top-center */}
              <circle cx={bx + BERTH_W / 2} cy={by + 6} r={3}
                fill={dotFill} />

              {/* Berth ID */}
              <text x={bx + BERTH_W / 2} y={by + BERTH_H - 5} textAnchor="middle"
                fill={labelC} fontSize={7} fontFamily="monospace" letterSpacing={0.5}
                fontWeight="600">
                {`B${String(i + 1).padStart(2, '0')}`}
              </text>
            </g>
          )
        })}

        {/* Terminal zone label */}
        <text x={14} y={PORT_Y + PORT_H - 6}
          fill="#0c1a28" fontSize={7.5} letterSpacing={2.5} fontFamily="monospace">
          TERMINAL BERTHS
        </text>

        {/* Operations suspended overlay */}
        {portClosed && (
          <g>
            <rect x={W / 2 - 170} y={PORT_Y + PORT_H / 2 - 12} width={340} height={24} rx={2}
              fill="#0c0404" stroke="#4a0e0e" strokeWidth={1} />
            <text x={W / 2} y={PORT_Y + PORT_H / 2 + 6} textAnchor="middle"
              fill="#ef4444" fontSize={11} fontWeight="700" letterSpacing={3} fontFamily="monospace">
              OPERATIONS SUSPENDED
            </text>
          </g>
        )}

        {/* ── Anchorage / Queue ── */}
        <rect x={0} y={QUEUE_Y} width={W} height={H - QUEUE_Y} fill="#030710" />
        <line x1={0} y1={QUEUE_Y} x2={W} y2={QUEUE_Y} stroke="#0a1624" strokeWidth={1} />

        <text x={14} y={QUEUE_Y + 13}
          fill="#0d1d2e" fontSize={7.5} letterSpacing={2.5} fontFamily="monospace">
          ANCHORAGE / WAITING AREA
        </text>

        {/* Queue fill bar */}
        {s.queueLength > 0 && (
          <rect x={200} y={QUEUE_Y + 6} width={Math.min(s.queueLength * 14, 380)} height={9}
            rx={1} fill={portClosed ? '#2e0a0a' : '#0b2050'} opacity={0.75} />
        )}
        <text x={590} y={QUEUE_Y + 14} fill="#162436" fontSize={8.5} fontFamily="monospace">
          {s.queueLength > 0 ? `${s.queueLength} VESSELS HOLDING` : 'QUEUE CLEAR'}
        </text>

        {/* ── Ships ── */}
        {s.ships.map(sh => {
          const paused = sh.status === 'in_berth' && portClosed
          return (
            <g key={sh.id}
              transform={`translate(${sh.x - SHIP_W / 2}, ${sh.y - SHIP_H / 2})`}>
              <polygon
                points={`0,${SHIP_H / 2} 5,0 ${SHIP_W},0 ${SHIP_W},${SHIP_H} 5,${SHIP_H}`}
                fill={paused ? '#240808' : sh.color}
                opacity={paused ? 0.3 : 0.85}
              />
              {paused && (
                <line x1={5} y1={SHIP_H / 2} x2={SHIP_W - 2} y2={SHIP_H / 2}
                  stroke="#ef4444" strokeWidth={1.5} opacity={0.45} />
              )}
            </g>
          )
        })}

        {/* ── Typhoon ── */}
        {t.phase !== 'none' && (
          <TyphoonSpiral x={t.x} y={t.y} scale={t.scale}
            rotation={t.rotation} cat={typhoonCat} phase={t.phase} />
        )}

        {/* ── Alert banners ── */}
        {t.phase === 'warning' && (
          <g>
            <rect x={W / 2 - 205} y={5} width={410} height={22} rx={2}
              fill="#0a0600" stroke="#92400e" strokeWidth={1} />
            <text x={W / 2} y={20} textAnchor="middle"
              fill="#fbbf24" fontSize={9.5} fontWeight="700" letterSpacing={1.5} fontFamily="monospace">
              METEOROLOGICAL ALERT — TYPHOON CAT {typhoonCat} — APPROACH DETECTED
            </text>
          </g>
        )}

        {t.phase === 'recovery' && !portClosed && (
          <g>
            <rect x={W / 2 - 200} y={PORT_Y + 4} width={400} height={20} rx={2}
              fill="#010e05" stroke="#0f4a20" strokeWidth={1} />
            <text x={W / 2} y={PORT_Y + 17} textAnchor="middle"
              fill="#4ade80" fontSize={9} fontWeight="700" letterSpacing={1.5} fontFamily="monospace">
              RESUMING OPERATIONS — CLEARING BACKLOG: {s.queueLength} VESSELS
            </text>
          </g>
        )}
      </svg>
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function HmiStat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ textAlign: 'right' }}>
      <div style={{ color: '#162030', fontSize: 8.5, letterSpacing: 1.5, fontFamily: 'monospace' }}>
        {label}
      </div>
      <div style={{ color, fontSize: 12, fontWeight: 700, fontFamily: 'monospace' }}>
        {value}
      </div>
    </div>
  )
}

function TyphoonSpiral({ x, y, scale, rotation, cat, phase }: {
  x: number; y: number; scale: number; rotation: number
  cat: number; phase: TyphoonPhase
}) {
  const colors = phase === 'impact'
    ? ['#dc2626', '#b91c1c', '#7f1d1d']
    : ['#3b82f6', '#2563eb', '#1d4ed8']
  const glow = phase === 'impact' ? 'rgba(180,25,25,0.10)' : 'rgba(37,99,235,0.08)'

  return (
    <g transform={`translate(${x},${y}) scale(${scale}) rotate(${rotation})`}>
      <circle r={12 + cat * 2.5} fill={glow} />
      <circle r={16} fill="none" stroke={colors[0]}
        strokeWidth={2.5 + cat * 0.25} strokeDasharray={`${18 + cat * 2} 8`} />
      <circle r={28} fill="none" stroke={colors[1]}
        strokeWidth={1.8} strokeDasharray={`${28 + cat * 2} 10`} opacity={0.75} />
      <circle r={42} fill="none" stroke={colors[2]}
        strokeWidth={1.2} strokeDasharray={`${40 + cat * 2} 14`} opacity={0.45} />
      {cat >= 4 && (
        <circle r={58} fill="none" stroke={colors[2]}
          strokeWidth={0.8} strokeDasharray="36 20" opacity={0.2} />
      )}
      <circle r={4} fill={phase === 'impact' ? '#fca5a5' : '#93c5fd'} opacity={0.85} />
      {/* Category callout box */}
      <rect x={-18} y={-36} width={36} height={13} rx={2}
        fill={phase === 'impact' ? '#120303' : '#020b1c'}
        stroke={colors[0]} strokeWidth={0.8} />
      <text y={-26} textAnchor="middle"
        fill={phase === 'impact' ? '#fca5a5' : '#93c5fd'}
        fontSize={8.5} fontWeight="700" fontFamily="monospace" letterSpacing={1}>
        CAT {cat}
      </text>
    </g>
  )
}
