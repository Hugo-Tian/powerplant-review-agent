import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, Table, Tag, Input, Select, Space, Typography, Badge } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import axios from 'axios'

const { Text } = Typography

interface TagRecord {
  id: number
  code: string
  name: string
  category: string
  weight: number
}

const CAT_CFG: Record<string, { color: string; label: string }> = {
  device_type: { color: '#00B4D8', label: '设备类型' },
  manufacturer: { color: '#fa8c16', label: '厂家' },
  model: { color: '#9c27b0', label: '型号' },
  fault_type: { color: '#ff4d4f', label: '故障类型' },
  keyword: { color: '#1677ff', label: '关键词' },
  component: { color: '#13c2c2', label: '部件' },
  action: { color: '#52c41a', label: '操作' },
  symptom: { color: '#eb2f96', label: '症状' },
  kks: { color: '#722ed1', label: 'KKS编码' },
}

// Tags page uses a different query that reads from schema
const getTags = () =>
  axios.get<TagRecord[]>('/api/admin/tags').then(r => r.data).catch(() => [] as TagRecord[])

export default function TagsPage() {
  const [kw, setKw] = useState('')
  const [catFilter, setCatFilter] = useState('')

  const { data: tags = [], isLoading } = useQuery({
    queryKey: ['tags'],
    queryFn: getTags,
    staleTime: 120_000,
  })

  const filtered = tags.filter(t => {
    if (catFilter && t.category !== catFilter) return false
    if (kw && !t.name.includes(kw) && !t.code.includes(kw)) return false
    return true
  })

  // Group stats
  const stats = Object.entries(CAT_CFG).map(([k, cfg]) => ({
    key: k,
    ...cfg,
    count: tags.filter(t => t.category === k).length,
  })).filter(s => s.count > 0)

  const columns: ColumnsType<TagRecord> = [
    {
      title: '标签代码',
      dataIndex: 'code',
      width: 180,
      render: v => (
        <Text style={{ fontFamily: 'monospace', fontSize: 11, color: '#a8a8bc' }}>{v}</Text>
      ),
    },
    {
      title: '名称',
      dataIndex: 'name',
      render: v => <Text style={{ fontSize: 13, color: '#e0e0e0' }}>{v}</Text>,
    },
    {
      title: '类别',
      dataIndex: 'category',
      width: 120,
      render: v => {
        const cfg = CAT_CFG[v] ?? { color: '#c0c0d0', label: v }
        return (
          <Tag
            style={{
              color: cfg.color, background: `${cfg.color}14`,
              border: `1px solid ${cfg.color}30`, fontSize: 11, borderRadius: 4,
            }}
          >
            {cfg.label}
          </Tag>
        )
      },
      filters: Object.entries(CAT_CFG).map(([k, v]) => ({ text: v.label, value: k })),
      onFilter: (v, r) => r.category === v,
    },
    {
      title: '权重',
      dataIndex: 'weight',
      width: 90,
      render: v => (
        <Text style={{ fontSize: 12, color: v >= 0.9 ? '#00B4D8' : '#a8a8bc', fontFamily: 'monospace' }}>
          {Number(v).toFixed(2)}
        </Text>
      ),
      sorter: (a, b) => b.weight - a.weight,
    },
  ]

  return (
    <div>
      {/* Category stats */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {stats.map(s => (
          <div
            key={s.key}
            onClick={() => setCatFilter(catFilter === s.key ? '' : s.key)}
            style={{
              background: catFilter === s.key ? `${s.color}20` : '#141414',
              border: `1px solid ${catFilter === s.key ? s.color : '#2a2a2a'}`,
              borderRadius: 8,
              padding: '8px 14px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              transition: 'all 0.2s',
            }}
          >
            <span style={{ fontSize: 11, color: catFilter === s.key ? s.color : '#c0c0d0' }}>{s.label}</span>
            <Badge
              count={s.count}
              style={{ background: catFilter === s.key ? s.color : '#2a2a2a', fontSize: 10 }}
            />
          </div>
        ))}
      </div>

      <Card
        style={{ background: '#111', border: '1px solid #1f1f1f' }}
        styles={{ body: { padding: 0 } }}
        title={
          <Space>
            <Input
              value={kw}
              onChange={e => setKw(e.target.value)}
              placeholder="搜索标签..."
              prefix={<SearchOutlined style={{ color: '#8888a0' }} />}
              style={{ width: 200 }}
              size="small"
              allowClear
            />
            <Select
              value={catFilter}
              onChange={setCatFilter}
              style={{ width: 130 }}
              size="small"
              options={[
                { value: '', label: '全部类别' },
                ...Object.entries(CAT_CFG).map(([k, v]) => ({ value: k, label: v.label })),
              ]}
            />
            <Text style={{ color: '#8888a0', fontSize: 12 }}>共 {filtered.length} 条</Text>
          </Space>
        }
      >
        <Table
          loading={isLoading}
          dataSource={filtered}
          columns={columns}
          rowKey="id"
          size="small"
          pagination={{ pageSize: 25, showTotal: t => `共 ${t} 条`, style: { padding: '8px 16px' } }}
        />
      </Card>
    </div>
  )
}
