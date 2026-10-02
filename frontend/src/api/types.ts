export interface PortAnimConfig {
  num_berths: number
  mean_interarrival_hrs: number
}

export interface ScenarioRow {
  scenario_id: number
  typhoon_cat: number
  dist_bin: number
  dist_range_km: string
  decreased_teu: number
  decreased_pct: number
  disruption_days_mean: number
  dz: number
  p_value: number
  is_significant: boolean
  is_significant_holm: boolean
  decision_signal: 'DIFFERENT_AND_MEANINGFUL' | 'STAT_SIGNIFICANT_BUT_PRACTICALLY_NEGLIGIBLE' | 'NOT_SIGNIFICANT'
  operationally_meaningful: boolean
}

export interface RunMetadata {
  run_id: string
  timestamp: string
  protocol_version: string
  design_doc_hash: string
  n_replications: number
  random_seed_base: number
}

export interface SimResultsResponse {
  run_metadata: RunMetadata
  intact_throughput_mean_teu: number
  n_replications: number
  port_anim: PortAnimConfig
  scenarios: ScenarioRow[]
}

export interface SimulateRequest {
  n_replications: number
}
