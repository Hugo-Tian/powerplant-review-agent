import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Row, Col, Tabs, Input, Select, Button, Card, Space, Tag, Typography,
  Spin, Empty, Divider, message, Tooltip, Badge,
} from 'antd'
import {
  ThunderboltOutlined, UserOutlined, ApartmentOutlined, WarningOutlined,
  CheckOutlined, LikeOutlined, DislikeOutlined, CloseOutlined, ReloadOutlined,
  DownloadOutlined, PaperClipOutlined,
} from '@ant-design/icons'
import {
  getPushList, runDailyPush, markRead, markClicked, submitFeedback,
  recordBehavior, rebuildProfile, getEventTags, getEventAttachments, CURRENT_USER_ID,
} from '../api/client'
import type { PushItem } from '../types'
import ScoreBadge from '../components/ScoreBadge'
import LevelTag from '../components/LevelTag'
import MetricCard from '../components/MetricCard'

const { Text } = Typography

const PUSH_TYPE_LABEL: Record<string, { label: string; color: string }> = {
  personal:     { label: '个性化', color: '#00B4D8' },
  device_group: { label: '同类设备', color: '#fa8c16' },
  emergency:    { label: '紧急推送', color: '#ff4d4f' },
}

function parsePushReasons(r: string[] | string): string[] {
  if (Array.isArray(r)) return r
  try { return JSON.parse(r) } catch { return [String(r)] }
}

const REASON_TAG_CONFIG: Record<string, { color: string }> = {
  '规则匹配':     { color: '#1677ff' },
  '画像匹配':     { color: '#00B4D8' },
  '同类设备关联': { color: '#fa8c16' },
  '紧急推送':     { color: '#ff4d4f' },
}

function reasonToTagLabel(reason: string): string {
  if (reason.includes('紧急')) return '紧急推送'
  if (reason.includes('同类设备') || reason.includes('厂家')) return '同类设备关联'
  if (reason.includes('负责的机组')) return '规则匹配'
  if (reason.includes('关注') || reason.includes('查询') || reason.includes('关键词')) return '画像匹配'
  return '规则匹配'
}

function PushCard({ item, onAction }: { item: PushItem; onAction: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const expandedAtRef = useRef<Date | null>(null)
  const qc = useQueryClient()
  const readMut = useMutation({ mutationFn: () => markRead(item.id), onSuccess: () => qc.invalidateQueries({ queryKey: ['push'] }) })
  const clickMut = useMutation({ mutationFn: () => markClicked(item.id), onSuccess: onAction })
  const feedMut = useMutation({
    mutationFn: (fb: string) => submitFeedback(item.id, fb),
    onSuccess: () => { message.success('反馈已提交'); qc.invalidateQueries({ queryKey: ['push'] }) },
  })
  const { data: eventTags = [] } = useQuery({
    queryKey: ['eventTags', item.event_id],
    queryFn: () => getEventTags(item.event_id),
    enabled: expanded,
    staleTime: 60_000,
  })
  const { data: attachments = [] } = useQuery({
    queryKey: ['attachments', item.event_id],
    queryFn: () => getEventAttachments(item.event_id),
    enabled: expanded,
    staleTime: 300_000,
  })

  const reasons = parsePushReasons(item.push_reasons)
  const reasonTagLabels = Array.from(new Set(reasons.map(reasonToTagLabel)))
  const typeInfo = PUSH_TYPE_LABEL[item.push_type] ?? { label: item.push_type, color: '#c0c0d0' }

  const handleExpand = () => {
    if (!expanded) {
      expandedAtRef.current = new Date()
      if (!item.is_read) readMut.mutate()
    }
    setExpanded(v => !v)
  }

  return (
    <Card
      onClick={handleExpand}
      style={{
        marginBottom: 10,
        cursor: 'pointer',
        background: expanded ? '#181818' : '#141414',
        border: `1px solid ${expanded ? '#00B4D820' : '#222222'}`,
        borderLeft: `3px solid ${
          item.level === '紧急' ? '#ff4d4f' : item.level === '重要' ? '#fa8c16' : '#52c41a'
        }`,
        transition: 'all 0.2s',
        opacity: item.is_read && !expanded ? 0.65 : 1,
      }}
      styles={{ body: { padding: '14px 16px' } }}
    >
      <Row align="middle" gutter={12} wrap={false}>
        {/* Left: info */}
        <Col flex="1" style={{ minWidth: 0 }}>
          <Space size={6} style={{ marginBottom: 4, flexWrap: 'wrap' }}>
            <Text style={{ fontSize: 11, color: '#8888a0', fontFamily: 'monospace' }}>
              {item.event_no}
            </Text>
            <LevelTag level={item.level} />
            <Tag
              style={{
                fontSize: 10, color: typeInfo.color,
                background: `${typeInfo.color}18`,
                border: `1px solid ${typeInfo.color}30`,
                borderRadius: 4, padding: '0 5px',
              }}
            >
              {typeInfo.label}
            </Tag>
            {item.is_read && (
              <Text style={{ fontSize: 10, color: '#6e6e80' }}>已读</Text>
            )}
          </Space>

          <div style={{ fontSize: 14, fontWeight: 600, color: '#e8e8e8', marginBottom: 4, lineHeight: 1.4 }}>
            {item.title.length > 50 ? item.title.slice(0, 50) + '…' : item.title}
          </div>

          <Space size={8} style={{ flexWrap: 'wrap' }}>
            {item.device_type_name && (
              <Tag color="blue" style={{ fontSize: 11 }}>{item.device_type_name}</Tag>
            )}
            {item.manufacturer_name && (
              <Tag color="orange" style={{ fontSize: 11 }}>{item.manufacturer_name}</Tag>
            )}
            {item.model_code && (
              <Tag style={{ fontSize: 11, fontFamily: 'monospace' }}>{item.model_code}</Tag>
            )}
            {reasonTagLabels.map((label, i) => {
              const cfg = REASON_TAG_CONFIG[label] ?? { color: '#8888a0' }
              return (
                <Tag key={i} style={{
                  fontSize: 10, color: cfg.color,
                  background: `${cfg.color}15`,
                  border: `1px solid ${cfg.color}30`,
                  borderRadius: 4, padding: '0 5px',
                }}>
                  {label}
                </Tag>
              )
            })}
            <Text style={{ fontSize: 11, color: '#8888a0' }}>
              {new Date(item.occurred_at).toLocaleString('zh-CN')}
            </Text>
          </Space>
        </Col>

        {/* Right: score */}
        <Col flex="none">
          <ScoreBadge score={item.match_score} />
        </Col>
      </Row>

      {/* Expanded detail */}
      {expanded && (
        <div onClick={e => e.stopPropagation()}>
          <Divider style={{ margin: '12px 0', borderColor: '#2a2a2a' }} />

          <div style={{ marginBottom: 10 }}>
            <Text style={{ fontSize: 11, color: '#9898b0', display: 'block', marginBottom: 6 }}>推送原因</Text>
            {reasons.map((r, i) => (
              <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 4, alignItems: 'flex-start' }}>
                <span style={{ color: '#00B4D8', fontSize: 11, marginTop: 2 }}>▸</span>
                <Text style={{ fontSize: 12, color: '#b0b0b0' }}>{r}</Text>
              </div>
            ))}
          </div>

          {/* Score breakdown */}
          <div style={{ marginBottom: 12 }}>
            <Text style={{ fontSize: 11, color: '#9898b0', display: 'block', marginBottom: 6 }}>维度得分</Text>
            <Row gutter={8}>
              {Object.entries(
                typeof item.score_breakdown === 'string'
                  ? (() => { try { return JSON.parse(item.score_breakdown) } catch { return {} } })()
                  : (item.score_breakdown || {})
              ).map(([k, v]) => (
                <Col key={k} span={6}>
                  <div style={{ background: '#1a1a1a', borderRadius: 6, padding: '6px 8px', textAlign: 'center' }}>
                    <div style={{ fontSize: 16, fontWeight: 700, color: '#00B4D8' }}>
                      {Math.round(parseFloat(String(v)) * 100)}
                    </div>
                    <div style={{ fontSize: 10, color: '#8888a0' }}>{k}</div>
                  </div>
                </Col>
              ))}
            </Row>
          </div>

          <Space size={8}>
            <Button
              size="small"
              type="primary"
              icon={<CheckOutlined />}
              onClick={() => {
                const enterTime = expandedAtRef.current ?? new Date()
                recordBehavior({
                  user_id: CURRENT_USER_ID,
                  module: '工单管理',
                  action_type: 'detail',
                  query_content: item.title,
                  selected_event_id: item.event_id,
                  data_type_tags: eventTags.length > 0 ? eventTags.map(t => t.code) : undefined,
                  enter_time: enterTime.toISOString(),
                  leave_time: new Date().toISOString(),
                }).then(() => rebuildProfile(CURRENT_USER_ID)).catch(() => {})
                clickMut.mutate()
              }}
              loading={clickMut.isPending}
              style={{ background: '#00B4D820', borderColor: '#00B4D8', color: '#00B4D8' }}
            >
              确认查看
            </Button>
            {attachments.length > 0 ? (
              attachments.map(att => (
                <Button
                  key={att.id}
                  size="small"
                  icon={<DownloadOutlined />}
                  onClick={() => {
                    recordBehavior({
                      user_id: CURRENT_USER_ID,
                      module: '工单管理',
                      action_type: 'download',
                      query_content: att.file_name,
                      selected_event_id: item.event_id,
                      data_type_tags: eventTags.length > 0 ? eventTags.map(t => t.code) : undefined,
                      enter_time: new Date().toISOString(),
                      leave_time: new Date().toISOString(),
                    }).then(() => rebuildProfile(CURRENT_USER_ID)).catch(() => {})
                    const a = document.createElement('a')
                    a.href = `/api/attachments/${att.id}/download`
                    a.download = att.file_name
                    document.body.appendChild(a)
                    a.click()
                    document.body.removeChild(a)
                  }}
                  style={{ color: '#8888a0', borderColor: '#333' }}
                >
                  {att.file_name.length > 12 ? att.file_name.slice(0, 12) + '…' : att.file_name}
                </Button>
              ))
            ) : (
              <Button size="small" icon={<PaperClipOutlined />} disabled style={{ color: '#555', borderColor: '#2a2a2a' }}>
                暂无附件
              </Button>
            )}
            <Tooltip title="有用">
              <Button
                size="small"
                icon={<LikeOutlined />}
                onClick={() => feedMut.mutate('like')}
                loading={feedMut.isPending}
                style={item.feedback === 'like' ? { color: '#52c41a', borderColor: '#52c41a' } : {}}
              />
            </Tooltip>
            <Tooltip title="无关">
              <Button
                size="small"
                icon={<DislikeOutlined />}
                onClick={() => feedMut.mutate('irrelevant')}
                loading={feedMut.isPending}
                style={item.feedback === 'irrelevant' ? { color: '#ff4d4f', borderColor: '#ff4d4f' } : {}}
              />
            </Tooltip>
            <Tooltip title="不感兴趣">
              <Button
                size="small"
                icon={<CloseOutlined />}
                onClick={() => feedMut.mutate('dislike')}
                loading={feedMut.isPending}
              />
            </Tooltip>
          </Space>
        </div>
      )}
    </Card>
  )
}

export default function PushPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState('all')
  const [levelFilter, setLevelFilter] = useState('')
  const [kwFilter, setKwFilter] = useState('')
  const [autoTriggered, setAutoTriggered] = useState(false)

  const { data: pushList = [], isLoading, error } = useQuery({
    queryKey: ['push', CURRENT_USER_ID],
    queryFn: () => getPushList(CURRENT_USER_ID),
    staleTime: 30_000,
  })

  const triggerMut = useMutation({
    mutationFn: runDailyPush,
    onSuccess: () => {
      setTimeout(() => qc.invalidateQueries({ queryKey: ['push'] }), 3000)
    },
  })

  // Auto-trigger push if empty on first load
  useEffect(() => {
    if (!isLoading && pushList.length === 0 && !autoTriggered && !error) {
      setAutoTriggered(true)
      triggerMut.mutate()
    }
  }, [isLoading, pushList.length, autoTriggered, error])

  // Filter
  let filtered = pushList
  if (tab !== 'all') filtered = filtered.filter(d => d.push_type === tab)
  if (levelFilter) filtered = filtered.filter(d => d.level === levelFilter)
  if (kwFilter) filtered = filtered.filter(d => d.title.toLowerCase().includes(kwFilter.toLowerCase()))

  const counts = {
    all: pushList.length,
    personal: pushList.filter(d => d.push_type === 'personal').length,
    device_group: pushList.filter(d => d.push_type === 'device_group').length,
    emergency: pushList.filter(d => d.push_type === 'emergency').length,
  }

  const tabItems = [
    { key: 'all', label: <span>全部 <Badge count={counts.all} color="#00B4D8" size="small" style={{ marginLeft: 2 }} /></span> },
    { key: 'personal', label: <span>个性化 <Badge count={counts.personal} color="#1677ff" size="small" style={{ marginLeft: 2 }} /></span> },
    { key: 'device_group', label: <span>同类设备 <Badge count={counts.device_group} color="#fa8c16" size="small" style={{ marginLeft: 2 }} /></span> },
    { key: 'emergency', label: <span>紧急事件 <Badge count={counts.emergency} color="#ff4d4f" size="small" style={{ marginLeft: 2 }} /></span> },
  ]

  return (
    <div>
      {/* Metrics */}
      <Row gutter={12} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <MetricCard title="今日推送" value={counts.all} color="#00B4D8" icon={<ThunderboltOutlined />} subtitle="来自推送引擎" />
        </Col>
        <Col span={6}>
          <MetricCard title="个性化推送" value={counts.personal} color="#1677ff" icon={<UserOutlined />} subtitle="画像匹配" />
        </Col>
        <Col span={6}>
          <MetricCard title="同类设备推送" value={counts.device_group} color="#fa8c16" icon={<ApartmentOutlined />} subtitle="设备组推送" />
        </Col>
        <Col span={6}>
          <MetricCard title="紧急事件" value={counts.emergency} color="#ff4d4f" icon={<WarningOutlined />} subtitle="优先推送" />
        </Col>
      </Row>

      {/* Tabs + Filter */}
      <Card style={{ background: '#111', border: '1px solid #1f1f1f' }} styles={{ body: { padding: 0 } }}>
        <div style={{ padding: '0 16px' }}>
          <Tabs
            activeKey={tab}
            onChange={setTab}
            items={tabItems}
            style={{ marginBottom: 0 }}
          />
        </div>
        <div style={{ padding: '10px 16px 14px', borderTop: '1px solid #1f1f1f', background: '#0d0d0d' }}>
          <Space>
            <Select
              value={levelFilter}
              onChange={setLevelFilter}
              style={{ width: 120 }}
              size="small"
              options={[
                { value: '', label: '全部等级' },
                { value: '紧急', label: '紧急' },
                { value: '重要', label: '重要' },
                { value: '一般', label: '一般' },
              ]}
            />
            <Input
              value={kwFilter}
              onChange={e => setKwFilter(e.target.value)}
              placeholder="搜索事件标题..."
              style={{ width: 200 }}
              size="small"
              allowClear
            />
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => { setLevelFilter(''); setKwFilter('') }}
            >
              重置
            </Button>
          </Space>
        </div>
      </Card>

      {/* List */}
      <div style={{ marginTop: 12 }}>
        {(isLoading || triggerMut.isPending) ? (
          <div style={{ textAlign: 'center', padding: '60px 0' }}>
            <Spin size="large" />
            <div style={{ color: '#9898b0', fontSize: 13, marginTop: 16 }}>
              {triggerMut.isPending ? '正在计算个性化匹配结果...' : '加载推送数据...'}
            </div>
          </div>
        ) : error ? (
          <div style={{ textAlign: 'center', padding: '40px 0', color: '#ff4d4f', fontSize: 13 }}>
            ⚠ 无法连接后端 API，请确认服务已启动
          </div>
        ) : filtered.length === 0 ? (
          <Empty
            description={<span style={{ color: '#9898b0' }}>暂无匹配推送数据</span>}
            style={{ padding: '60px 0' }}
          />
        ) : (
          filtered.map(item => (
            <PushCard
              key={item.id}
              item={item}
              onAction={() => qc.invalidateQueries({ queryKey: ['push'] })}
            />
          ))
        )}
      </div>
    </div>
  )
}
