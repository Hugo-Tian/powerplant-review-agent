export interface PushItem {
  id: number
  event_id: string
  event_no: string
  title: string
  level: '紧急' | '重要' | '一般' | '建议'
  event_type: string | null
  occurred_at: string
  status: string
  device_type_name: string | null
  manufacturer_name: string | null
  model_code: string | null
  match_score: number
  score_breakdown: Record<string, number>
  push_reasons: string[] | string
  push_type: 'personal' | 'device_group' | 'emergency'
  is_read: boolean
  is_clicked: boolean
  feedback: 'like' | 'dislike' | 'irrelevant' | null
  read_at: string | null
}

export interface EventItem {
  id: string
  event_no: string
  title: string
  level: string
  event_type: string | null
  status: string
  occurred_at: string
  device_type_name: string | null
  manufacturer_name: string | null
}

export interface EventTag {
  code: string
  name: string
  category: string
  confidence: number
  extract_method: string
  extracted_at: string
}

export interface EventAttachment {
  id: string
  file_name: string
  file_type: string | null
  file_size: number | null
  storage_url: string
  created_at: string
}

export interface BehaviorRecord {
  id: number
  action_type: string
  module: string | null
  query_content: string | null
  data_type_tags: string[] | null
  stay_duration_sec: number | null
  mouse_max_stay_sec: number | null
  enter_time: string
}

export interface UserProfile {
  user_id: string
  role: string
  responsible_units: string[]
  device_interests: Record<string, number>
  mfr_interests: Record<string, number>
  fault_interests: Record<string, number>
  keyword_interests: Record<string, number>
  personal_tags?: string[]
  last_computed_at?: string
}

export interface TagRecord {
  id: number
  code: string
  name: string
  category: string
  weight: number
}

export interface PushStat {
  push_date: string
  total: number
  read_count: number
  click_count: number
  avg_score: number
}

export interface PushConfig {
  score_threshold: number
  max_push_per_day: number
  weight_device_type: number
  weight_behavior: number
  weight_role: number
  weight_manufacturer: number
  push_window_start: string
  push_window_end: string
  channel_in_app: boolean
  channel_mobile: boolean
  channel_email: boolean
  emergency_realtime: boolean
}
