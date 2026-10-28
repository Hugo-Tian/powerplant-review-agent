import axios from 'axios'
import type { PushItem, EventItem, EventTag, BehaviorRecord, UserProfile, TagRecord, PushStat } from '../types'

export const CURRENT_USER_ID = '00000000-0000-0000-0000-000000000001'
export const SESSION_ID = crypto.randomUUID()

const http = axios.create({
  baseURL: '',
  timeout: 15000,
})

// ── Health ──────────────────────────────────────────────
export const checkHealth = () =>
  http.get<{ status: string; time: string }>('/health').then(r => r.data)

// ── Push ────────────────────────────────────────────────
export const getPushList = (userId: string, pageSize = 50) =>
  http.get<PushItem[]>(`/api/users/${userId}/push`, { params: { page_size: pageSize } }).then(r => r.data)

export const runDailyPush = () =>
  http.post('/api/admin/run-daily-push').then(r => r.data)

export const getPushStats = (days = 14) =>
  http.get<PushStat[]>('/api/admin/push-stats', { params: { days } }).then(r => r.data)

export const markRead = (pushId: number) =>
  http.patch(`/api/push/${pushId}/read`).then(r => r.data)

export const markClicked = (pushId: number) =>
  http.patch(`/api/push/${pushId}/click`).then(r => r.data)

export const submitFeedback = (pushId: number, feedback: string) =>
  http.patch(`/api/push/${pushId}/feedback`, { feedback }).then(r => r.data)

// ── Events ──────────────────────────────────────────────
export const getEvents = (params: {
  plant_id?: number
  device_type_id?: number
  level?: string
  keyword?: string
  page?: number
  page_size?: number
}) => http.get<{ total: number; page: number; page_size: number; items: EventItem[] }>('/api/events', { params }).then(r => r.data)

export const getEventTags = (eventId: string) =>
  http.get<EventTag[]>(`/api/events/${eventId}/tags`).then(r => r.data)

export const getEventAttachments = (eventId: string) =>
  http.get<import('../types').EventAttachment[]>(`/api/events/${eventId}/attachments`).then(r => r.data)

export const triggerExtract = (eventId: string) =>
  http.post(`/api/events/${eventId}/extract-tags`).then(r => r.data)

// ── Behaviors ───────────────────────────────────────────
export const getUserBehaviors = (userId: string, days = 30, page = 1) =>
  http.get<BehaviorRecord[]>(`/api/users/${userId}/behaviors`, { params: { days, page, page_size: 100 } }).then(r => r.data)

export const recordBehavior = (payload: {
  user_id: string
  module?: string
  action_type: string
  query_content?: string
  query_fields?: Record<string, unknown>
  selected_event_id?: string
  data_type_tags?: string[]
  result_count?: number
  enter_time: string
  leave_time?: string
}) =>
  http.post('/api/behaviors', { session_id: SESSION_ID, ...payload }).then(r => r.data)

// ── Profile ─────────────────────────────────────────────
export const getUserProfile = (userId: string) =>
  http.get<UserProfile>(`/api/users/${userId}/profile`).then(r => r.data)

export const rebuildProfile = (userId: string) =>
  http.post(`/api/users/${userId}/profile/rebuild`).then(r => r.data)

// ── Tags ────────────────────────────────────────────────
export const getAllTags = () =>
  http.get<TagRecord[]>('/api/admin/tags').then(r => r.data)
