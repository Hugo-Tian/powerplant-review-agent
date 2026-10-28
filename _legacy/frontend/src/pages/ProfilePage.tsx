import { useMemo } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  Row, Col, Card, Avatar, Tag, Typography, Space, Button, Spin, Tooltip, message,
} from 'antd'
import { ReloadOutlined, UserOutlined, ClusterOutlined } from '@ant-design/icons'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer, RadarChart,
  Radar, PolarGrid, PolarAngleAxis, Cell,
} from 'recharts'
import { getUserProfile, rebuildProfile, getAllTags, CURRENT_USER_ID } from '../api/client'

const { Text } = Typography

const TAG_COLORS = ['#00B4D8', '#1677ff', '#52c41a', '#fa8c16', '#9c27b0', '#ff4d4f', '#13c2c2']

function InterestBarChart({ data, color }: { data: { name: string; value: number }[]; color: string }) {
  if (!data.length) return <Text style={{ color: '#8888a0', fontSize: 12 }}>暂无数据</Text>
  return (
    <ResponsiveContainer width="100%" height={Math.max(data.length * 32, 100)}>
      <BarChart data={data} layout="vertical" margin={{ left: 0, right: 30, top: 4, bottom: 4 }}>
        <XAxis type="number" domain={[0, 1]} tickCount={6} allowDecimals={false} tick={{ fontSize: 10, fill: '#8888a0' }} tickFormatter={v => `${Math.round(v * 100)}%`} />
        <YAxis type="category" dataKey="name" width={90} tick={{ fontSize: 11, fill: '#c0c0d0' }} />
        <RTooltip
          contentStyle={{ background: '#1a1a1a', border: '1px solid #2a2a2a', borderRadius: 6, fontSize: 11 }}
          formatter={(v: number) => [`${Math.round(v * 100)}%`, '权重']}
        />
        <Bar dataKey="value" radius={[0, 4, 4, 0]}>
          {data.map((_, i) => (
            <Cell key={i} fill={color} opacity={0.5 + (data.length - i) / data.length * 0.5} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

function MfrRadarChart({ data }: { data: { subject: string; value: number }[] }) {
  if (!data.length) return <Text style={{ color: '#8888a0', fontSize: 12 }}>暂无数据</Text>
  return (
    <ResponsiveContainer width="100%" height={200}>
      <RadarChart data={data} margin={{ top: 10, right: 10, bottom: 10, left: 10 }}>
        <PolarGrid stroke="#2a2a2a" />
        <PolarAngleAxis dataKey="subject" tick={{ fontSize: 11, fill: '#c0c0d0' }} />
        <Radar dataKey="value" stroke="#00B4D8" fill="#00B4D8" fillOpacity={0.15} strokeWidth={2} />
        <RTooltip
          contentStyle={{ background: '#1a1a1a', border: '1px solid #2a2a2a', borderRadius: 6, fontSize: 11 }}
          formatter={(v: number) => [`${Math.round(v * 100)}%`, '偏好']}
        />
      </RadarChart>
    </ResponsiveContainer>
  )
}

export default function ProfilePage() {
  const { data: profile, isLoading } = useQuery({
    queryKey: ['profile', CURRENT_USER_ID],
    queryFn: () => getUserProfile(CURRENT_USER_ID),
    staleTime: 60_000,
  })

  const { data: allTags = [] } = useQuery({
    queryKey: ['allTags'],
    queryFn: getAllTags,
    staleTime: 300_000,
  })

  const tagName = useMemo(() => {
    const m: Record<string, string> = {}
    for (const t of allTags) m[t.code] = t.name
    return m
  }, [allTags])

  const rebuildMut = useMutation({
    mutationFn: () => rebuildProfile(CURRENT_USER_ID),
    onSuccess: () => message.success('画像重建已启动，稍后刷新'),
  })

  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: '60px 0' }}>
        <Spin size="large" />
      </div>
    )
  }

  // Merge entries with the same display name (different codes for same concept)
  const mergeByName = (interests: Record<string, number>) => {
    const grouped: Record<string, number> = {}
    for (const [k, v] of Object.entries(interests)) {
      const name = tagName[k] ?? k
      grouped[name] = Math.max(grouped[name] ?? 0, v)
    }
    return Object.entries(grouped).sort(([, a], [, b]) => b - a)
  }

  const deviceData = mergeByName(profile?.device_interests ?? {})
    .slice(0, 8)
    .map(([name, value]) => ({ name, value }))

  const mfrData = mergeByName(profile?.mfr_interests ?? {})
    .slice(0, 6)
    .map(([name, value]) => ({ subject: name, value }))

  const faultData = mergeByName(profile?.fault_interests ?? {})
    .slice(0, 8)
    .map(([name, value]) => ({ name, value }))

  const keywords = mergeByName(profile?.keyword_interests ?? {}).slice(0, 15)

  const maxKw = keywords[0]?.[1] ?? 1  // keywords is [name, value][]

  const initials = (profile?.user_id === CURRENT_USER_ID) ? '张建' : '用户'

  return (
    <Row gutter={[16, 16]}>
      {/* Left column */}
      <Col xs={24} md={7}>
        <Card
          style={{ background: '#141414', border: '1px solid #1f1f1f', marginBottom: 16 }}
          styles={{ body: { padding: 20 } }}
        >
          <div style={{ textAlign: 'center', marginBottom: 16 }}>
            <Avatar
              size={64}
              style={{ background: 'linear-gradient(135deg, #00B4D8, #0077A8)', fontSize: 20, fontWeight: 700, marginBottom: 12 }}
              icon={<UserOutlined />}
            >
              {initials}
            </Avatar>
            <div style={{ fontSize: 17, fontWeight: 600, color: '#e8e8e8' }}>张建国</div>
            <div style={{ fontSize: 12, color: '#a8a8bc', marginTop: 2 }}>
              {profile?.role ?? '—'} · 汽轮机部
            </div>
          </div>

          <div style={{ borderTop: '1px solid #2a2a2a', paddingTop: 12 }}>
            <Row style={{ marginBottom: 8 }}>
              <Col span={12}><Text style={{ fontSize: 11, color: '#9898b0' }}>负责机组</Text></Col>
              <Col span={12}>
                <Text style={{ fontSize: 12, color: '#b0b0b0' }}>
                  {(profile?.responsible_units ?? []).join(' · ') || '—'}
                </Text>
              </Col>
            </Row>
            <Row>
              <Col span={12}><Text style={{ fontSize: 11, color: '#9898b0' }}>画像更新</Text></Col>
              <Col span={12}>
                <Text style={{ fontSize: 11, color: '#a8a8bc', fontFamily: 'monospace' }}>
                  {profile?.last_computed_at
                    ? new Date(profile.last_computed_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
                    : '—'}
                </Text>
              </Col>
            </Row>
          </div>

          <Button
            block
            size="small"
            icon={<ReloadOutlined />}
            loading={rebuildMut.isPending}
            onClick={() => rebuildMut.mutate()}
            style={{ marginTop: 16, background: '#1a1a1a', borderColor: '#2a2a2a', color: '#c0c0d0' }}
          >
            重建画像
          </Button>
        </Card>

        {/* Keyword cloud */}
        <Card
          title={<span style={{ fontSize: 12, color: '#9898b0' }}>关键词兴趣</span>}
          style={{ background: '#141414', border: '1px solid #1f1f1f' }}
          styles={{ body: { padding: 16 }, header: { borderBottom: '1px solid #1f1f1f', background: '#0f0f0f', minHeight: 40 } }}
        >
          <Space wrap size={6}>
            {keywords.map(([name, w], i) => {
              const fs = Math.round(11 + (w / maxKw) * 7)
              return (
                <Tooltip key={name} title={`权重 ${Math.round(w * 100)}%`}>
                  <Tag
                    style={{
                      fontSize: fs,
                      color: TAG_COLORS[i % TAG_COLORS.length],
                      background: `${TAG_COLORS[i % TAG_COLORS.length]}14`,
                      border: `1px solid ${TAG_COLORS[i % TAG_COLORS.length]}30`,
                      cursor: 'default',
                      padding: '2px 8px',
                    }}
                  >
                    {name}
                  </Tag>
                </Tooltip>
              )
            })}
            {keywords.length === 0 && <Text style={{ color: '#8888a0', fontSize: 12 }}>暂无数据</Text>}
          </Space>
        </Card>
      </Col>

      {/* Right column */}
      <Col xs={24} md={17}>
        <Row gutter={[16, 16]}>
          <Col span={24}>
            <Card
              title={<span style={{ fontSize: 12, color: '#9898b0' }}>设备类型兴趣分布</span>}
              extra={<ClusterOutlined style={{ color: '#8888a0' }} />}
              style={{ background: '#141414', border: '1px solid #1f1f1f' }}
              styles={{ body: { padding: 16 }, header: { borderBottom: '1px solid #1f1f1f', background: '#0f0f0f', minHeight: 40 } }}
            >
              <InterestBarChart data={deviceData} color="#00B4D8" />
            </Card>
          </Col>

          <Col span={12}>
            <Card
              title={<span style={{ fontSize: 12, color: '#9898b0' }}>厂家偏好</span>}
              style={{ background: '#141414', border: '1px solid #1f1f1f' }}
              styles={{ body: { padding: '16px 8px' }, header: { borderBottom: '1px solid #1f1f1f', background: '#0f0f0f', minHeight: 40 } }}
            >
              <MfrRadarChart data={mfrData} />
            </Card>
          </Col>

          <Col span={12}>
            <Card
              title={<span style={{ fontSize: 12, color: '#9898b0' }}>故障类型关注</span>}
              style={{ background: '#141414', border: '1px solid #1f1f1f' }}
              styles={{ body: { padding: 16 }, header: { borderBottom: '1px solid #1f1f1f', background: '#0f0f0f', minHeight: 40 } }}
            >
              <InterestBarChart data={faultData} color="#fa8c16" />
            </Card>
          </Col>
        </Row>
      </Col>
    </Row>
  )
}
