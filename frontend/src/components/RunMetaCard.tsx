import { Card, Tag, Typography, Divider } from 'antd'
import type { RunMetadata } from '../api/types'

const { Text } = Typography

interface Props {
  metadata: RunMetadata
  intactTeu: number
  nReplications: number
}

export default function RunMetaCard({ metadata, intactTeu, nReplications }: Props) {
  const ts = new Date(metadata.timestamp).toLocaleString('en-GB', {
    dateStyle: 'short', timeStyle: 'short',
  })

  return (
    <Card size="small"
      style={{ background: '#0f1729', border: '1px solid #1e293b', borderRadius: 12 }}
      styles={{ body: { padding: 14 } }}>

      <Text style={{ color: '#94a3b8', fontSize: 11, display: 'block', marginBottom: 10 }}>
        RUN METADATA
      </Text>

      {/* Intact throughput */}
      <div style={{ marginBottom: 10 }}>
        <Text style={{ color: '#475569', fontSize: 11 }}>Intact throughput</Text>
        <div>
          <Text style={{ color: '#38bdf8', fontSize: 22, fontWeight: 700 }}>
            {(intactTeu / 1e6).toFixed(2)}M
          </Text>
          <Text style={{ color: '#475569', fontSize: 12 }}> TEU/year</Text>
        </div>
      </div>

      <Divider style={{ borderColor: '#1e293b', margin: '8px 0' }} />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <MetaRow label="Replications" value={`${nReplications}`} color="#a78bfa" />
        <MetaRow label="Method" value={metadata.protocol_version} color="#34d399" />
        <MetaRow label="Doc hash" value={metadata.design_doc_hash} color="#fb923c" mono />
        <MetaRow label="Run ID" value={metadata.run_id.slice(0, 8) + '…'} color="#64748b" mono />
        <MetaRow label="Timestamp" value={ts} color="#64748b" />
      </div>

      <Divider style={{ borderColor: '#1e293b', margin: '10px 0 6px' }} />

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <Tag color="blue" style={{ fontSize: 10 }}>CRN ✓</Tag>
        <Tag color="green" style={{ fontSize: 10 }}>Holm-Bonferroni ✓</Tag>
        <Tag color="orange" style={{ fontSize: 10 }}>Annualized ✓</Tag>
      </div>
    </Card>
  )
}

function MetaRow({ label, value, color, mono = false }: {
  label: string; value: string; color: string; mono?: boolean
}) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Text style={{ color: '#475569', fontSize: 11 }}>{label}</Text>
      <Text style={{
        color, fontSize: 11,
        fontFamily: mono ? 'monospace' : undefined,
        maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>
        {value}
      </Text>
    </div>
  )
}
