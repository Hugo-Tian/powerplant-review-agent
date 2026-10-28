import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Row, Col, Card, Slider, InputNumber, Switch, Button, Typography, Space,
  Divider, Alert, message, Spin,
} from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined, ReloadOutlined,
  SettingOutlined, ThunderboltOutlined, CodeOutlined,
} from '@ant-design/icons'
import { checkHealth, runDailyPush, getPushStats } from '../api/client'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from 'recharts'

const { Text, Title } = Typography

const DIM_LABELS: Record<string, string> = {
  weight_device_type: '设备类型',
  weight_behavior: '行为数据',
  weight_role: '岗位职责',
  weight_manufacturer: '制造商',
}

export default function ConfigPage() {
  const qc = useQueryClient()
  const [threshold, setThreshold] = useState(60)
  const [maxPush, setMaxPush] = useState(20)
  const [weights, setWeights] = useState({
    weight_device_type: 35,
    weight_behavior: 30,
    weight_role: 20,
    weight_manufacturer: 15,
  })

  const weightSum = Object.values(weights).reduce((a, b) => a + b, 0)

  const { data: health, isLoading: healthLoading, refetch: refetchHealth } = useQuery({
    queryKey: ['health'],
    queryFn: checkHealth,
    staleTime: 10_000,
    retry: 1,
  })

  const { data: stats = [], isLoading: statsLoading } = useQuery({
    queryKey: ['pushStats'],
    queryFn: () => getPushStats(14),
    staleTime: 60_000,
  })

  const pushMut = useMutation({
    mutationFn: runDailyPush,
    onSuccess: () => {
      message.success('推送计算已启动（后台运行）')
      setTimeout(() => qc.invalidateQueries({ queryKey: ['push'] }), 3500)
    },
    onError: () => message.error('触发失败，请检查服务状态'),
  })

  // Format stats for chart
  const chartData = [...stats]
    .sort((a, b) => a.push_date.localeCompare(b.push_date))
    .map(s => ({
      date: s.push_date.slice(5),
      推送: s.total,
      已读: s.read_count,
      点击: s.click_count,
    }))

  const isOnline = !!health?.status && health.status === 'ok'

  return (
    <Row gutter={[16, 16]}>
      {/* Left: Config */}
      <Col xs={24} md={12}>
        <Card
          title={<span style={{ fontSize: 13, color: '#c0c0d0', display: 'flex', alignItems: 'center', gap: 8 }}><SettingOutlined />推送规则配置</span>}
          style={{ background: '#141414', border: '1px solid #1f1f1f' }}
          styles={{ header: { borderBottom: '1px solid #1f1f1f', background: '#0f0f0f' }, body: { padding: 20 } }}
        >
          {/* Threshold */}
          <div style={{ marginBottom: 24 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <Text style={{ fontSize: 12, color: '#c0c0d0' }}>匹配分数阈值</Text>
              <Text style={{ fontSize: 14, fontWeight: 700, color: '#00B4D8', fontFamily: 'monospace' }}>{threshold}%</Text>
            </div>
            <Slider
              value={threshold}
              onChange={setThreshold}
              min={0} max={100}
              trackStyle={{ background: '#00B4D8' }}
              handleStyle={{ borderColor: '#00B4D8', background: '#141414' }}
              marks={{ 40: '40%', 60: '60%', 80: '80%' }}
            />
            <Text style={{ fontSize: 11, color: '#8888a0' }}>低于此分数的事件不推送</Text>
          </div>

          {/* Max push */}
          <div style={{ marginBottom: 24 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <Text style={{ fontSize: 12, color: '#c0c0d0' }}>每日最大推送数</Text>
              <InputNumber
                value={maxPush}
                onChange={v => setMaxPush(v ?? 20)}
                min={5} max={50}
                size="small"
                style={{ width: 80, fontFamily: 'monospace' }}
              />
            </div>
            <Slider
              value={maxPush}
              onChange={setMaxPush}
              min={5} max={50}
              trackStyle={{ background: '#fa8c16' }}
              handleStyle={{ borderColor: '#fa8c16', background: '#141414' }}
            />
          </div>

          <Divider style={{ borderColor: '#2a2a2a', margin: '16px 0' }} />

          {/* Dimension weights */}
          <div style={{ marginBottom: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
              <Text style={{ fontSize: 12, color: '#c0c0d0' }}>维度权重配置</Text>
              <Text style={{ fontSize: 11, color: weightSum === 100 ? '#52c41a' : '#ff4d4f', fontFamily: 'monospace' }}>
                合计：{weightSum}%
              </Text>
            </div>
            {Object.entries(weights).map(([k, v]) => (
              <div key={k} style={{ marginBottom: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <Text style={{ fontSize: 12, color: '#a8a8bc' }}>{DIM_LABELS[k]}</Text>
                  <Text style={{ fontSize: 12, fontFamily: 'monospace', color: '#b0b0b0' }}>{v}%</Text>
                </div>
                <Slider
                  value={v}
                  onChange={val => setWeights(prev => ({ ...prev, [k]: val ?? 0 }))}
                  min={0} max={50}
                  trackStyle={{ background: '#00B4D860' }}
                  handleStyle={{ borderColor: '#00B4D8', background: '#141414' }}
                />
              </div>
            ))}
          </div>

          {weightSum !== 100 && (
            <Alert
              message={`维度权重合计为 ${weightSum}%，建议调整为 100%`}
              type="warning"
              showIcon
              style={{ marginBottom: 12, fontSize: 11 }}
            />
          )}

          <Button
            type="primary"
            block
            icon={<ThunderboltOutlined />}
            loading={pushMut.isPending}
            onClick={() => pushMut.mutate()}
            style={{ background: '#00B4D820', borderColor: '#00B4D8', color: '#00B4D8', marginTop: 4 }}
          >
            手动触发今日推送计算
          </Button>
        </Card>
      </Col>

      {/* Right: System status + stats */}
      <Col xs={24} md={12}>
        <Card
          title={<span style={{ fontSize: 13, color: '#c0c0d0', display: 'flex', alignItems: 'center', gap: 8 }}><CodeOutlined />系统状态</span>}
          style={{ background: '#141414', border: '1px solid #1f1f1f', marginBottom: 16 }}
          styles={{ header: { borderBottom: '1px solid #1f1f1f', background: '#0f0f0f' }, body: { padding: 20 } }}
        >
          <div style={{ marginBottom: 12 }}>
            <Text style={{ fontSize: 11, color: '#8888a0', display: 'block', marginBottom: 6 }}>后端 API 地址</Text>
            <div style={{
              fontFamily: 'monospace', fontSize: 12, background: '#0d0d0d',
              padding: '8px 12px', borderRadius: 6, color: '#a8a8bc',
              border: '1px solid #1f1f1f',
            }}>
              http://localhost:8000
            </div>
          </div>

          <div style={{ marginBottom: 16 }}>
            <Text style={{ fontSize: 11, color: '#8888a0', display: 'block', marginBottom: 8 }}>API 健康状态</Text>
            {healthLoading ? (
              <Spin size="small" />
            ) : isOnline ? (
              <Space>
                <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 16 }} />
                <Text style={{ color: '#52c41a', fontSize: 13 }}>连接正常</Text>
                <Text style={{ fontSize: 11, color: '#8888a0', fontFamily: 'monospace' }}>
                  {health?.time ? new Date(health.time).toLocaleTimeString('zh-CN') : ''}
                </Text>
              </Space>
            ) : (
              <Space>
                <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 16 }} />
                <Text style={{ color: '#ff4d4f', fontSize: 13 }}>连接失败</Text>
              </Space>
            )}
          </div>

          <Space>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => refetchHealth()}>
              刷新检查
            </Button>
            <Button
              size="small"
              icon={<ThunderboltOutlined />}
              onClick={() => pushMut.mutate()}
              loading={pushMut.isPending}
            >
              触发推送
            </Button>
          </Space>

          <Divider style={{ borderColor: '#2a2a2a', margin: '16px 0' }} />

          <div>
            <Text style={{ fontSize: 11, color: '#8888a0', display: 'block', marginBottom: 8 }}>推送时间窗口</Text>
            <div style={{ display: 'flex', gap: 8 }}>
              {['channel_in_app', 'channel_mobile', 'channel_email'].map(ch => (
                <div key={ch} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <Switch size="small" defaultChecked={ch !== 'channel_email'} />
                  <Text style={{ fontSize: 11, color: '#a8a8bc' }}>
                    {ch === 'channel_in_app' ? '站内' : ch === 'channel_mobile' ? '移动端' : '邮件'}
                  </Text>
                </div>
              ))}
            </div>
          </div>
        </Card>

        {/* Stats chart */}
        <Card
          title={<span style={{ fontSize: 13, color: '#c0c0d0' }}>近14天推送统计</span>}
          style={{ background: '#141414', border: '1px solid #1f1f1f' }}
          styles={{ header: { borderBottom: '1px solid #1f1f1f', background: '#0f0f0f' }, body: { padding: '16px 8px' } }}
        >
          {statsLoading ? (
            <div style={{ textAlign: 'center', padding: 20 }}><Spin /></div>
          ) : chartData.length === 0 ? (
            <Text style={{ color: '#8888a0', fontSize: 12, display: 'block', textAlign: 'center', padding: 20 }}>暂无数据</Text>
          ) : (
            <ResponsiveContainer width="100%" height={180}>
              <LineChart data={chartData} margin={{ left: -10, right: 10, top: 4, bottom: 4 }}>
                <CartesianGrid stroke="#1f1f1f" strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#8888a0' }} />
                <YAxis tick={{ fontSize: 10, fill: '#8888a0' }} />
                <Tooltip
                  contentStyle={{ background: '#1a1a1a', border: '1px solid #2a2a2a', borderRadius: 6, fontSize: 11 }}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line type="monotone" dataKey="推送" stroke="#00B4D8" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="已读" stroke="#52c41a" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="点击" stroke="#fa8c16" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Card>
      </Col>
    </Row>
  )
}
