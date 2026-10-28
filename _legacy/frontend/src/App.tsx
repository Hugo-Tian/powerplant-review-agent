import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Layout, Menu, Avatar, Typography, Button, Space, Badge,
} from 'antd'
import {
  ThunderboltOutlined, FileTextOutlined, UserOutlined, BarChartOutlined,
  TagsOutlined, SettingOutlined, ReloadOutlined,
} from '@ant-design/icons'
import { checkHealth, runDailyPush, CURRENT_USER_ID } from './api/client'
import { useQueryClient, useMutation } from '@tanstack/react-query'
import StatusDot from './components/StatusDot'

import PushPage from './pages/PushPage'
import EventsPage from './pages/EventsPage'
import BehaviorPage from './pages/BehaviorPage'
import ProfilePage from './pages/ProfilePage'
import TagsPage from './pages/TagsPage'
import ConfigPage from './pages/ConfigPage'

const { Sider, Header, Content } = Layout
const { Text } = Typography

const PAGE_TITLES: Record<string, string> = {
  push: '今日事件推送',
  events: '事件信息库',
  behavior: '用户行为记录',
  profile: '用户画像',
  tags: '标签管理',
  config: '推送配置',
}

const NAV_ITEMS = [
  { key: 'push',     icon: <ThunderboltOutlined />, label: '今日推送' },
  { key: 'events',   icon: <FileTextOutlined />,    label: '事件信息库' },
  { key: 'behavior', icon: <UserOutlined />,        label: '用户行为记录' },
  { key: 'profile',  icon: <BarChartOutlined />,    label: '用户画像' },
  { key: 'tags',     icon: <TagsOutlined />,        label: '标签管理' },
  { key: 'config',   icon: <SettingOutlined />,     label: '推送配置' },
]

export default function App() {
  const [page, setPage] = useState('push')
  const qc = useQueryClient()

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: checkHealth,
    staleTime: 15_000,
    refetchInterval: 30_000,
    retry: 1,
  })

  const triggerMut = useMutation({
    mutationFn: runDailyPush,
    onSuccess: () => {
      setTimeout(() => qc.invalidateQueries({ queryKey: ['push'] }), 3000)
    },
  })

  const isOnline = !!health?.status && health.status === 'ok'
  const today = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })

  return (
    <Layout style={{ height: '100vh', background: '#0a0a0a' }}>
      {/* Sidebar */}
      <Sider
        width={210}
        style={{
          background: '#0d0d0d',
          borderRight: '1px solid #1a1a1a',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Logo */}
        <div style={{
          padding: '18px 16px 14px',
          borderBottom: '1px solid #1a1a1a',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              width: 32, height: 32, borderRadius: 8,
              background: 'linear-gradient(135deg, #00B4D8, #0077A8)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0,
            }}>
              <ThunderboltOutlined style={{ color: '#fff', fontSize: 16 }} />
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#e8e8e8', lineHeight: 1.3 }}>智能工单推送</div>
              <div style={{ fontSize: 10, color: '#8888a0', lineHeight: 1.3 }}>Power Plant IMS</div>
            </div>
          </div>
        </div>

        {/* Nav */}
        <Menu
          mode="inline"
          theme="dark"
          selectedKeys={[page]}
          onSelect={({ key }) => setPage(key)}
          items={NAV_ITEMS}
          style={{
            background: '#0d0d0d',
            border: 'none',
            flex: 1,
            paddingTop: 8,
          }}
        />

        {/* User */}
        <div style={{
          padding: '12px 16px',
          borderTop: '1px solid #1a1a1a',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}>
          <Avatar
            size={30}
            style={{ background: 'linear-gradient(135deg, #00B4D8, #0077A8)', fontSize: 11, fontWeight: 700, flexShrink: 0 }}
          >
            张建
          </Avatar>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: '#c0c0c0', lineHeight: 1.3 }}>张建国</div>
            <StatusDot online={isOnline} />
          </div>
        </div>
      </Sider>

      {/* Main */}
      <Layout style={{ background: '#0a0a0a' }}>
        {/* Header */}
        <Header style={{
          background: '#111111',
          borderBottom: '1px solid #1a1a1a',
          padding: '0 20px',
          height: 52,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}>
          <Text style={{ fontSize: 15, fontWeight: 600, color: '#e8e8e8' }}>
            {PAGE_TITLES[page]}
          </Text>

          <Space size={12}>
            <Text style={{ fontSize: 12, color: '#6e6e80', fontFamily: 'monospace' }}>{today}</Text>
            <Badge
              status={isOnline ? 'success' : 'error'}
              text={
                <Text style={{ fontSize: 12, color: isOnline ? '#52c41a' : '#ff4d4f' }}>
                  {isOnline ? '● 服务正常' : '● 服务异常'}
                </Text>
              }
            />
            {page === 'push' && (
              <Button
                size="small"
                type="primary"
                icon={<ReloadOutlined spin={triggerMut.isPending} />}
                loading={triggerMut.isPending}
                onClick={() => triggerMut.mutate()}
                style={{ background: '#00B4D820', borderColor: '#00B4D840', color: '#00B4D8', fontSize: 12 }}
              >
                重新匹配
              </Button>
            )}
          </Space>
        </Header>

        {/* Content */}
        <Content style={{ padding: '16px 20px', overflowY: 'auto' }}>
          {page === 'push'     && <PushPage />}
          {page === 'events'   && <EventsPage />}
          {page === 'behavior' && <BehaviorPage />}
          {page === 'profile'  && <ProfilePage />}
          {page === 'tags'     && <TagsPage />}
          {page === 'config'   && <ConfigPage />}
        </Content>
      </Layout>
    </Layout>
  )
}
