import { useState, useRef, useCallback, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Card, Table, Tag, Input, Select, Space, Button, Typography, Spin, Tooltip,
} from 'antd'
import { SearchOutlined, ReloadOutlined, TagsOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { getEvents, getEventTags, recordBehavior, rebuildProfile, CURRENT_USER_ID } from '../api/client'
import type { EventItem, EventTag } from '../types'
import LevelTag from '../components/LevelTag'

const { Text } = Typography

const STATUS_COLOR: Record<string, string> = {
  open: '#fa8c16',
  processing: '#00B4D8',
  closed: '#52c41a',
}
const STATUS_LABEL: Record<string, string> = {
  open: '待处理',
  processing: '处理中',
  closed: '已关闭',
}

const TAG_CAT_COLOR: Record<string, string> = {
  device_type: 'blue',
  manufacturer: 'orange',
  fault_type: 'red',
  keyword: 'purple',
  symptom: 'cyan',
  component: 'geekblue',
  action: 'green',
}

function EventTagRow({ eventId, onRecord }: { eventId: string; onRecord?: (tags: EventTag[]) => void }) {
  const { data: tags = [], isLoading } = useQuery({
    queryKey: ['eventTags', eventId],
    queryFn: () => getEventTags(eventId),
    staleTime: 60_000,
  })
  const firedRef = useRef(false)

  useEffect(() => {
    if (!isLoading && !firedRef.current) {
      firedRef.current = true
      onRecord?.(tags)
    }
  }, [isLoading]) // eslint-disable-line react-hooks/exhaustive-deps

  if (isLoading) return <Spin size="small" />
  if (!tags.length) return <Text style={{ color: '#8888a0', fontSize: 12 }}>暂无 NLP 标签</Text>

  return (
    <Space wrap size={4}>
      {tags.map(t => (
        <Tooltip key={t.code} title={`置信度 ${Math.round(t.confidence * 100)}%  |  ${t.extract_method}`}>
          <Tag color={TAG_CAT_COLOR[t.category] ?? 'default'} style={{ fontSize: 11, cursor: 'default' }}>
            {t.name}
          </Tag>
        </Tooltip>
      ))}
    </Space>
  )
}

export default function EventsPage() {
  const [level, setLevel] = useState('')
  const [keyword, setKw] = useState('')
  const [page, setPage] = useState(1)
  const [expandedRowKeys, setExpandedRowKeys] = useState<string[]>([])
  const expandEnterRef = useRef<Record<string, Date>>({})
  const expandTagsRef = useRef<Record<string, EventTag[]>>({})

  const { data, isLoading } = useQuery({
    queryKey: ['events', level, keyword, page],
    queryFn: () => getEvents({ level: level || undefined, keyword: keyword || undefined, page, page_size: 20 }),
    staleTime: 30_000,
  })

  const doSearch = () => {
    recordBehavior({
      user_id: CURRENT_USER_ID,
      module: '事件信息库',
      action_type: 'query',
      query_content: keyword || undefined,
      query_fields: { level: level || undefined, keyword: keyword || undefined },
      result_count: data?.total,
      enter_time: new Date().toISOString(),
    }).catch(() => {})
    setPage(1)
  }

  const handleTagsLoaded = useCallback((eventId: string, tags: EventTag[]) => {
    expandTagsRef.current[eventId] = tags
  }, [])

  const columns: ColumnsType<EventItem> = [
    {
      title: '事件编号',
      dataIndex: 'event_no',
      width: 160,
      render: v => (
        <Text style={{ fontFamily: 'monospace', fontSize: 11, color: '#9898b0' }}>{v}</Text>
      ),
    },
    {
      title: '标题',
      dataIndex: 'title',
      render: (v, rec) => (
        <div>
          <div style={{ fontSize: 13, color: '#e0e0e0', marginBottom: 2 }}>{v}</div>
          {rec.event_type && (
            <Text style={{ fontSize: 11, color: '#8888a0' }}>{rec.event_type}</Text>
          )}
        </div>
      ),
    },
    {
      title: '等级',
      dataIndex: 'level',
      width: 80,
      filters: [
        { text: '紧急', value: '紧急' },
        { text: '重要', value: '重要' },
        { text: '一般', value: '一般' },
        { text: '建议', value: '建议' },
      ],
      render: v => <LevelTag level={v} />,
    },
    {
      title: '设备类型',
      dataIndex: 'device_type_name',
      width: 110,
      render: v => v ? <Tag color="blue" style={{ fontSize: 11 }}>{v}</Tag> : <Text style={{ color: '#6e6e80' }}>—</Text>,
    },
    {
      title: '厂家',
      dataIndex: 'manufacturer_name',
      width: 110,
      render: v => v ? <Tag color="orange" style={{ fontSize: 11 }}>{v}</Tag> : <Text style={{ color: '#6e6e80' }}>—</Text>,
    },
    {
      title: '发生时间',
      dataIndex: 'occurred_at',
      width: 150,
      render: v => (
        <Text style={{ fontSize: 11, color: '#a8a8bc', fontFamily: 'monospace' }}>
          {new Date(v).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
        </Text>
      ),
      sorter: (a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime(),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 85,
      render: v => (
        <Tag
          style={{
            color: STATUS_COLOR[v] ?? '#c0c0d0',
            background: `${STATUS_COLOR[v] ?? '#c0c0d0'}18`,
            border: `1px solid ${STATUS_COLOR[v] ?? '#c0c0d0'}30`,
            fontSize: 11, borderRadius: 4,
          }}
        >
          {STATUS_LABEL[v] ?? v}
        </Tag>
      ),
    },
  ]

  return (
    <div>
      <Card
        style={{ background: '#111', border: '1px solid #1f1f1f', marginBottom: 12 }}
        styles={{ body: { padding: '12px 16px' } }}
      >
        <Space>
          <Select
            value={level}
            onChange={setLevel}
            style={{ width: 120 }}
            size="small"
            options={[
              { value: '', label: '全部等级' },
              { value: '紧急', label: '紧急' },
              { value: '重要', label: '重要' },
              { value: '一般', label: '一般' },
              { value: '建议', label: '建议' },
            ]}
          />
          <Input
            value={keyword}
            onChange={e => setKw(e.target.value)}
            onPressEnter={doSearch}
            placeholder="关键词搜索..."
            prefix={<SearchOutlined style={{ color: '#8888a0' }} />}
            style={{ width: 200 }}
            size="small"
            allowClear
          />
          <Button size="small" type="primary" icon={<SearchOutlined />} onClick={doSearch}>
            查询
          </Button>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => { setLevel(''); setKw(''); setPage(1) }}>
            重置
          </Button>
          <Text style={{ color: '#8888a0', fontSize: 12 }}>
            共 {data?.total ?? '—'} 条记录
          </Text>
        </Space>
      </Card>

      <Card
        style={{ background: '#111', border: '1px solid #1f1f1f' }}
        styles={{ body: { padding: 0 } }}
      >
        <Table
          loading={isLoading}
          dataSource={data?.items ?? []}
          columns={columns}
          rowKey="id"
          size="small"
          expandable={{
            expandedRowKeys,
            onExpand: (expanded, record) => {
              if (!expanded) {
                const enterTime = expandEnterRef.current[record.id]
                const tags = expandTagsRef.current[record.id] ?? []
                if (enterTime) {
                  recordBehavior({
                    user_id: CURRENT_USER_ID,
                    module: '事件信息库',
                    action_type: 'detail',
                    query_content: record.title,
                    selected_event_id: record.id,
                    data_type_tags: tags.map(t => t.code),
                    enter_time: enterTime.toISOString(),
                    leave_time: new Date().toISOString(),
                  }).then(() => rebuildProfile(CURRENT_USER_ID)).catch(() => {})
                }
              }
              setExpandedRowKeys(expanded ? [record.id] : [])
              if (expanded) {
                expandEnterRef.current[record.id] = new Date()
              }
            },
            expandedRowRender: record => (
              <div style={{ padding: '8px 16px', background: '#0d0d0d' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <TagsOutlined style={{ color: '#8888a0', fontSize: 12 }} />
                  <Text style={{ fontSize: 11, color: '#8888a0' }}>NLP 提取标签</Text>
                </div>
                <EventTagRow
                  eventId={record.id}
                  onRecord={tags => handleTagsLoaded(record.id, tags)}
                />
              </div>
            ),
          }}
          pagination={{
            current: page,
            pageSize: 20,
            total: data?.total ?? 0,
            onChange: setPage,
            showSizeChanger: false,
            showTotal: t => `共 ${t} 条`,
            style: { padding: '8px 16px' },
          }}
          rowClassName={() => 'event-row'}
        />
      </Card>
    </div>
  )
}
