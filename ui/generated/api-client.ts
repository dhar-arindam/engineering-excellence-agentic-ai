/**
 * Auto-generated API types — matches backend Pydantic models (snake_case).
 * Run `npm run generate:api` to regenerate when the backend schema changes.
 */

// ─── Primitive enum types ──────────────────────────────────────────────────────

export type RiskLevel = 'Low' | 'Medium' | 'High' | 'Critical';
export type Severity = 'Critical' | 'High' | 'Medium' | 'Low' | 'Info';
export type AgentType = 'QA' | 'Dev' | 'Architect' | 'SRE' | 'Security';
export type ImpactLevel = 'Low' | 'Medium' | 'High';
export type ScanOperationMode = 'analyze' | 'suggest' | 'auto-fix';
export type ScanStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
export type ScanMode = 'quick' | 'standard' | 'security_only' | 'deep';
export type ScanDepth = 'shallow' | 'standard' | 'deep';
export type SourceType = 'github' | 'local';
export type LogLevel = 'debug' | 'info' | 'warn' | 'error' | 'success';

// ─── Agent scores ──────────────────────────────────────────────────────────────

export interface AgentScore {
  agent: AgentType;
  score: number;
  delta: number;
  issue_count: number;
  description: string;
  /** Agent confidence 0–1 in its own assessment. */
  confidence: number;
  /** Human-readable explanation of the confidence level. */
  confidence_reason: string;
}

// ─── Radar chart ──────────────────────────────────────────────────────────────

/** Single axis of the 6-dimension radar chart. */
export interface RadarDimension {
  /** Score 0–10 for this dimension. */
  score: number;
  /** Confidence 0–1 for this dimension's data. */
  confidence: number;
}

export interface RadarData {
  readability: RadarDimension;
  complexity: RadarDimension;
  reliability: RadarDimension;
  security: RadarDimension;
  maintainability: RadarDimension;
  stability: RadarDimension;
}

// ─── Issues ───────────────────────────────────────────────────────────────────

export interface Issue {
  id: string;
  severity: Severity;
  agent: AgentType;
  file_path: string;
  line_number: number;
  title: string;
  description: string;
  recommendation: string;
}

// ─── Architecture drift ───────────────────────────────────────────────────────

export interface ArchitectureDrift {
  circular_dependency_delta: number;
  layer_violations_delta: number;
  coupling_delta: string;
  previous_circular: number;
  current_circular: number;
  previous_violations: number;
  current_violations: number;
}

// ─── Trend ────────────────────────────────────────────────────────────────────

export interface TrendPoint {
  label: string;
  score: number;
  date: string;
}

// ─── Fix report shapes ────────────────────────────────────────────────────────

export interface ValidationReport {
  lint_passed: boolean;
  tests_passed: boolean;
  type_check_passed: boolean;
  errors: string[];
}

export interface BreakingChangeReport {
  has_breaking_changes: boolean;
  details: string[];
}

export interface FixPR {
  created: boolean;
  pr_url?: string;
}

// ─── Patch annotation shapes ──────────────────────────────────────────────────

export interface HunkAnnotation {
  /** Zero-based index of the @@ hunk this annotation applies to. */
  hunk_index: number;
  /** Human-readable explanation of why this change was made. */
  reason: string;
  /** Numeric risk score 1–10 for this modification. */
  risk_score: number;
  risk_level: RiskLevel;
  impact: ImpactLevel;
  /** References to issue IDs, CVE numbers, or rule names. */
  references?: string[];
}

export interface FileAnnotation {
  /** Path as it appears in the +++ b/ diff header. */
  file: string;
  impact: ImpactLevel;
  /** Overall risk score 1–10 for all changes in this file. */
  risk_score: number;
  hunks: HunkAnnotation[];
}

export interface PatchAnnotations {
  files: FileAnnotation[];
  overall_impact: ImpactLevel;
}

// ─── Scan ─────────────────────────────────────────────────────────────────────

export interface ScanSummary {
  id: string;
  repository_id: string;
  repository_name: string;
  branch: string;
  commit_sha: string;
  date: string;
  status: ScanStatus;
  mode: ScanMode;
  operation_mode: ScanOperationMode;
  source_type: SourceType;
  overall_score: number;
  risk: RiskLevel;
  delta: number;
  duration: string;
  issue_count: number;
}

export interface Scan extends ScanSummary {
  repository_url?: string;
  agents: AgentScore[];
  issues: Issue[];
  drift: ArchitectureDrift;
  read_only: boolean;
  patch_available: boolean;
  validation_report?: ValidationReport;
  breaking_change_report?: BreakingChangeReport;
  fix_pr?: FixPR;
  /** Weighted average confidence across all agents (0–1). */
  overall_confidence: number;
  /** 6-dimension radar chart data. Empty for old scans. */
  radar: Partial<RadarData>;
  /** Top issues sorted Critical > High > Medium > Low. */
  top_risks: Issue[];
}

// ─── Repository ───────────────────────────────────────────────────────────────

export interface RepositoryListItem {
  id: string;
  name: string;
  description: string;
  language: string;
  source_type: SourceType;
  repository_url?: string;
  local_path?: string;
  overall_score: number;
  delta: number;
  risk: RiskLevel;
  last_scan_date: string;
  open_issues: number;
  team_size: number;
  scan_count: number;
}

export interface Repository extends RepositoryListItem {
  agents: AgentScore[];
  trend: TrendPoint[];
  scans: ScanSummary[];
}

// ─── Agents performance ───────────────────────────────────────────────────────

export interface AgentRecentScore {
  scan_id: string;
  repository_name: string;
  score: number;
  date: string;
}

export interface AgentPerformanceEntry {
  name: AgentType;
  avg_score: number;
  total_runs: number;
  description: string;
  recent_scores: AgentRecentScore[];
}

export interface AgentsPerformanceResponse {
  agents: AgentPerformanceEntry[];
  total_scans_analysed: number;
}

// ─── Security overview ────────────────────────────────────────────────────────

export interface SecurityRepoEntry {
  repository_id: string;
  repository_name: string;
  security_score: number;
  risk: RiskLevel;
  open_issues: number;
  last_scan_date: string;
  scan_id: string;
}

export interface SecurityOverviewResponse {
  repositories: SecurityRepoEntry[];
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
}

// ─── Trend analysis ──────────────────────────────────────────────────────────

/** Radar dimension for a trend data point. null when scan predates radar tracking. */
export interface TrendRadarDimension {
  score: number | null;
  confidence: number | null;
}

export interface TrendDataPoint {
  /** ISO-8601 UTC timestamp of the scan. */
  timestamp: string;
  overall_score: number;
  /** Agent-derived confidence at scan time (0–1). */
  overall_confidence: number;
  /** Confidence after exponential time-decay — older scans weigh less. */
  effective_confidence: number;
  /** 6-dimension radar scores. Empty object for old scans. */
  radar: Partial<Record<string, TrendRadarDimension>>;
}

export interface AggregatedTrend {
  /** Decay-weighted average overall score. */
  overall_score: number;
  /** Mean effective confidence across the window. */
  confidence: number;
  /** Set when average effective_confidence < 0.5. */
  trend_warning?: string | null;
}

export interface RepositoryTrends {
  repo_id: string;
  /** Scan history ordered oldest-first. */
  time_series: TrendDataPoint[];
  aggregated_trend: AggregatedTrend;
}

// ─── Auth ─────────────────────────────────────────────────────────────────────

export interface LocalUser {
  name: string;
  email: string;
  id: string;
  roles?: string[];
}

// ─── Repository request/response ─────────────────────────────────────────────

export interface CreateRepositoryRequest {
  name: string;
  description?: string;
  language?: string;
  source_type: SourceType;
  repository_url?: string;
  local_path?: string;
  team_size?: number;
}

export interface UpdateRepositoryRequest {
  name?: string;
  description?: string;
  language?: string;
  team_size?: number;
}

export interface RepositoryListResponse {
  items: RepositoryListItem[];
  total: number;
}

// ─── Scan request/response ────────────────────────────────────────────────────

export interface ScanConfig {
  mode: ScanMode;
  /** Only applies when mode is 'standard' or 'deep' */
  depth: ScanDepth;
  /** Subset of agents to run; all five by default */
  agents: AgentType[];
  /** What to do with findings — defaults to 'analyze' */
  operation_mode: ScanOperationMode;
}

export type ScanSourceType = SourceType;

export interface RunScanRequest {
  source_type: ScanSourceType;
  /** Required when source_type is 'github' */
  repository_url?: string;
  /** Required when source_type is 'local' */
  local_path?: string;
  /** Target branch (GitHub only) */
  branch?: string;
  config: ScanConfig;
}

export interface RunScanResponse {
  scan_id: string;
  repository_id: string;
  status: Extract<ScanStatus, 'queued' | 'running'>;
  estimated_seconds?: number;
}

export interface ScanStatusResponse {
  status: ScanStatus;
  progress_percentage: number;
  current_step?: string;
  error_message?: string;
  elapsed_seconds?: number;
  estimated_remaining_seconds?: number;
}

export interface ScanListParams {
  repository_id?: string;
  status?: ScanStatus;
  limit?: number;
  offset?: number;
}

export interface ScanListResponse {
  items: ScanSummary[];
  total: number;
}

export interface CreatePRResponse {
  created: boolean;
  pr_url?: string;
  message?: string;
}

// ─── Branch API ───────────────────────────────────────────────────────────────

export interface BranchesResponse {
  branches: string[];
  default_branch: string;
}

// ─── Pull Requests API ────────────────────────────────────────────────────────

export interface PullRequestItem {
  number: number;
  title: string;
  /** 'open' | 'closed' */
  state: string;
  draft: boolean;
  /** Head branch being merged */
  head_ref: string;
  /** Base branch (merge target) */
  base_ref: string;
  author: string;
  url: string;
  created_at: string;
  updated_at: string;
}

export interface PullRequestsResponse {
  pull_requests: PullRequestItem[];
  total: number;
}

// ─── WebSocket / Log streaming ────────────────────────────────────────────────

export interface ScanLogEntry {
  id: string;
  timestamp: string;
  level: LogLevel;
  message: string;
  agent?: AgentType;
  /** Logical phase label, e.g. "clone", "qa-analysis" */
  step?: string;
  metadata?: Record<string, unknown>;
}

// ─── UI helpers ───────────────────────────────────────────────────────────────

export interface RecentRepo {
  value: string;
  source_type: ScanSourceType;
  /** Short display label, e.g. "owner/repo" */
  label: string;
  last_used: string;
  default_branch?: string;
}

export interface EstimatedTime {
  min: number;
  max: number;
  label: string;
}
