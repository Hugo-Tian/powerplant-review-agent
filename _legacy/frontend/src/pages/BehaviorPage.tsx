import { useQuery } from '@tanstack/react-query'
import { Card, Table, Tag, Progress, Typography, Space } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { getUserBehaviors, CURRENT_USER_ID } from '../api/client'
import type { BehaviorRecord } from '../types'
import MetricCard from '../components/MetricCard'
import { Row, Col } from 'antd'
import { ClockCircleOutlined, SearchOutlined, FileTextOutlined, DownloadOutlined } from '@ant-design/icons'

const { Text } = Typography

const ACTION_CFG: Record<string, { color: string; label: string }> = {
  query:    { color: '#00B4D8', label: '查询' },
  detail:   { color: '#52c41a', label: '详情' },
  export:   { color: '#9c27b0', label: '导出' },
  download: { color: '#fa8c16', label: '下载' },
  share:    { color: '#1677ff', label: '分享' },
  print:    { color: '#c0c0d0', label: '打印' },
}

export default function BehaviorPage() {
  const { data: behaviors = [], isLoading } = useQuery({
    queryKey: ['behaviors', CURRENT_USER_ID],
    queryFn: () => getUserBehaviors(CURRENT_USER_ID, 30),
    staleTime: 60_000,
  })

  const counts = {
    total: behaviors.length,
    query: behaviors.filter(b => b.action_type === 'query').length,
    detail: behaviors.filter(b => b.action_type === 'detail').length,
    download: behaviors.filter(b => b.action_type === 'download').length,
  }
  const avgStay = behaviors.length
    ? Math.round(behaviors.reduce((s, b) => s + (b.stay_duration_sec ?? 0), 0) / behaviors.length)
    : 0

  const columns: ColumnsType<BehaviorRecord> = [
    {
      title: '操作时间',
      dataIndex: 'enter_time',
      width: 140,
      render: v => (
        <Text style={{ fontSize: 11, fontFamily: 'monospace', color: '#a8a8bc' }}>
          {new Date(v).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
        </Text>
      ),
      sorter: (a, b) => new Date(b.enter_time).getTime() - new Date(a.enter_time).getTime(),
    },
    {
      title: '行为类型',
      dataIndex: 'action_type',
      width: 90,
      render: v => {
        const cfg = ACTION_CFG[v] ?? { color: '#c0c0d0', label: v }
        return (
          <Tag style={{ color: cfg.color, background: `${cfg.color}18`, border: `1px solid ${cfg.color}30`, fontSize: 11, borderRadius: 4 }}>
            {cfg.label}
          </Tag>
        )
      },
    },
    {
      title: '访问模块',
      dataIndex: 'module',
      width: 110,
      render: v => <Text style={{ fontSize: 12, color: '#c0c0d0' }}>{v ?? '—'}</Text>,
    },
    {
      title: '查询内容',
      dataIndex: 'query_content',
      render: v => v ? (
        <Text style={{ fontSize: 12, color: '#b0b0b0' }}>{v}</Text>
      ) : <Text style={{ color: '#6e6e80' }}>—</Text>,
    },
    {
      title: '数据标签',
      dataIndex: 'data_type_tags',
      width: 180,
      render: (v: string[] | null) => {
        if (!v?.length) return <Text style={{ color: '#6e6e80' }}>—</Text>
        const tags = Array.isArray(v) ? v : JSON.parse(v as unknown as string)
        return (
          <Space wrap size={3}>
            {(tags as string[]).slice(0, 3).map(t => (
              <Tag key={t} style={{ fontSize: 10, padding: '0 4px' }}>{t.replace('tag_', '')}</Tag>
            ))}
            {tags.length > 3 && <Text style={{ fontSize: 10, color: '#8888a0' }}>+{tags.length - 3}</Text>}
          </Space>
        )
      },
    },
    {
      title: '停留时长',
      dataIndex: 'stay_duration_sec',
      width: 130,
      render: v => {
        if (!v) return <Text style={{ color: '#6e6e80' }}>—</Text>
        const max = 600
        const pct = Math.min(Math.round((v / max) * 100), 100)
        const color = v > 300 ? '#00B4D8' : v > 120 ? '#52c41a' : '#fa8c16'
        return (
          <div style={{ minWidth: 100 }}>
            <div style={{ fontSize: 11, color, marginBottom: 2 }}>{v}s</div>
            <Progress percent={pct} size={[80, 4]} showInfo={false} strokeColor={color} trailColor="#1f1f1f" />
          </div>
        )
      },
      sorter: (a, b) => (b.stay_duration_sec ?? 0) - (a.stay_duration_sec ?? 0),
    },
    {
      title: '鼠标停留',
      dataIndex: 'mouse_max_stay_sec',
      width: 90,
      render: v => v ? (
        <Text style={{ fontSize: 11, color: '#a8a8bc' }}>{v}s</Text>
      ) : <Text style={{ color: '#6e6e80' }}>—</Text>,
    },
  ]

  return (
    <div>
      <Row gutter={12} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <MetricCard title="近30天行为" value={counts.total} color="#00B4D8" icon={<ClockCircleOutlined />} />
        </Col>
        <Col span={6}>
          <MetricCard title="查询次数" value={counts.query} color="#1677ff" icon={<SearchOutlined />} />
        </Col>
        <Col span={6}>
          <MetricCard title="详情查看" value={counts.detail} color="#52c41a" icon={<FileTextOutlined />} />
        </Col>
        <Col span={6}>
          <MetricCard title="平均停留" value={avgStay} suffix="s" color="#fa8c16" icon={<DownloadOutlined />} subtitle="每次行为" />
        </Col>
      </Row>

      <Card
        title={<span style={{ fontSize: 13, color: '#c0c0d0' }}>行为日志明细</span>}
        extra={<Tag color="cyan" style={{ fontSize: 11 }}>实时数据</Tag>}
        style={{ background: '#111', border: '1px solid #1f1f1f' }}
        styles={{ body: { padding: 0 }, header: { borderBottom: '1px solid #1f1f1f', background: '#0d0d0d' } }}
      >
        <Table
          loading={isLoading}
          dataSource={behaviors}
          columns={columns}
          rowKey="id"
          size="small"
          pagination={{ pageSize: 20, showTotal: t => `共 ${t} 条`, style: { padding: '8px 16px' } }}
        />
      </Card>
    </div>
  )
}
