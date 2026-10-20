export type TemporalKind =
  | 'sequential'
  | 'parallel'
  | 'partial_overlap'
  | 'same_start'
  | 'same_finish'
  | 'gap'

export type RelationType = 'FS' | 'SS' | 'FF' | 'SF'

export type TemporalRelation = {
  predecessor_activity_id: string
  successor_activity_id: string
  kind: TemporalKind
  gap_days: number
  overlap_days: number
  start_delta_days: number
  finish_delta_days: number
}

export type CanonicalMatch = {
  activity_id: string
  source_name: string
  canonical_work_id: string | null
  canonical_work_code: string | null
  canonical_work_name: string | null
  mapping_status: 'MATCHED' | 'AMBIGUOUS' | 'UNMAPPED'
  candidates: {id: string; code: string; name: string; score: number}[]
  needs_confirmation: boolean
}

export type ProposedDependency = {
  id: string
  predecessor_activity_id: string
  successor_activity_id: string
  relation_type: RelationType
  lag_days: number
  rule_id: string | null
  confidence: 'high' | 'medium' | 'low'
  status: 'proposed' | 'confirmed' | 'rejected'
  requires_confirmation: boolean
  reason: string
  source: 'rule' | 'excel' | 'user' | 'calendar'
  scope_key?: string | null
  chain?: string | null
}

export type ProposalGroup = {
  id: string
  title: string
  relation_type: RelationType
  confidence: 'high' | 'medium' | 'low'
  proposal_ids: string[]
  scope_count: number
  lag_min: number
  lag_max: number
  chain: string | null
  chain_label: string | null
  recommended: boolean
  status: 'proposed' | 'confirmed' | 'rejected' | 'mixed'
}

export type NetworkRecoverySummary = {
  activities_loaded: number
  proposed_count: number
  need_confirmation: number
  unlinked_count: number
  excel_deps_kept: number
  ambiguous_mappings: number
  temporal_pairs: number
  group_count: number
  auto_ready: number
}

export type NetworkRecoveryModel = {
  analyzed_at: string
  original_calendar: {activity_id: string; planned_start: string | null; planned_end: string | null}[]
  temporal_relations: TemporalRelation[]
  canonical_matches: CanonicalMatch[]
  proposed: ProposedDependency[]
  groups: ProposalGroup[]
  summary: NetworkRecoverySummary
  /** До подтверждения сетевой модели прогноз — предварительный */
  forecast_mode: 'preliminary' | 'confirmed'
}

export type DependencyRule = {
  id: string
  predecessor_aliases: string[]
  successor_aliases: string[]
  relation: RelationType
  lag_mode: 'calendar_fs' | 'calendar_ss' | 'calendar_ff' | 'fixed'
  fixed_lag?: number
  confidence: 'high' | 'medium' | 'low'
  requires_confirmation: boolean
  note?: string
  chain?: string
}
