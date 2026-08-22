export interface AnalysisSummary {
  global_bias_cents: number
  mean_absolute_error_cents: number
  relative_mean_absolute_error_cents?: number
  within_15_percent?: number
  within_25_percent: number
  within_50_percent: number
  relative_within_15_percent?: number
  relative_within_25_percent?: number
  relative_within_50_percent?: number
  valid_frame_count: number
  valid_fraction?: number
  matched_seconds?: number
  stable_note_pitch_center_mae_cents?: number | null
  relative_stable_note_pitch_center_mae_cents?: number | null
  stable_note_region_count?: number
  stable_note_total_seconds?: number
}

export interface StablePitchRegion {
  reference_start: number
  reference_end: number
  reference_center_midi: number
  performance_center_midi: number
  error_cents: number
  relative_error_cents: number
}

export interface AnalysisFrames {
  reference_time: number[]
  performance_time: number[]
  reference_midi: number[]
  performance_midi: number[]
  confidence: number[]
  reference_confidence?: number[]
  performance_confidence?: number[]
  reference_voiced?: boolean[]
  performance_voiced?: boolean[]
  valid: boolean[]
  absolute_error_cents: number[]
  relative_error_cents: number[]
}

export interface AnalysisArtifact {
  created_at: string
  configuration?: { pitch_confidence_threshold?: number }
  alignment?: {
    frames_per_second?: number
    global_offset_seconds?: number | null
    global_offset_confidence?: number | null
    global_offset_method?: string | null
    global_offset_applied?: boolean
  }
  reference: {
    source: { path: string; duration_seconds: number }
    original_mix: { path: string; duration_seconds: number } | null
  }
  performance: {
    source: { path: string; duration_seconds: number }
    original_mix?: { path: string; duration_seconds: number } | null
  }
  comparison: {
    summary: AnalysisSummary
    frames: AnalysisFrames
    stable_pitch_regions?: StablePitchRegion[]
  }
  warnings: string[]
}

export interface ProjectReference {
  title: string
  source_type: "youtube" | "local"
  source_url: string | null
  original_path: string
  vocal_path: string
  instrumental_path: string | null
  duration_seconds: number
  sample_rate: number
  separation_model: string | null
  separation_cached: boolean
}

export interface Take {
  id: string
  name: string
  created_at: string
  source_path: string
  isolate_performance: boolean
  status: "ready" | "analyzing" | "analyzed" | "failed"
  analysis_path: string | null
  analysis_summary: AnalysisSummary | null
  error: string | null
}

export interface Project {
  id: string
  title: string
  created_at: string
  updated_at: string
  reference: ProjectReference
  lyrics: string
  trim_start_seconds: number
  trim_end_seconds: number | null
  transpose_semitones: number
  takes: Take[]
}

export interface WaveformEnvelope {
  time: number[]
  amplitude: number[]
}

export interface AlignedWaveforms {
  time: number[]
  reference_amplitude: number[]
  performance_amplitude: number[]
}
