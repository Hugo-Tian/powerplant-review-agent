import { Card, Statistic } from 'antd'
import type { ReactNode } from 'react'

interface Props {
  title: string
  value: number | string
  suffix?: string
  color?: string
  icon?: ReactNode
  subtitle?: string
}

export default function MetricCard({ title, value, suffix, color = '#e8e8e8', icon, subtitle }: Props) {
  return (
    <Card
      style={{
        background: 'linear-gradient(135deg, #161616 0%, #111111 100%)',
        border: '1px solid #2a2a2a',
        borderRadius: 12,
      }}
      styles={{ body: { padding: '16px 20px' } }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 11, color: '#9898b0', letterSpacing: '0.5px', marginBottom: 8, textTransform: 'uppercase' }}>
            {title}
          </div>
          <Statistic
            value={value}
            suffix={suffix}
            valueStyle={{ fontSize: 28, fontWeight: 700, color, lineHeight: 1 }}
          />
          {subtitle && (
            <div style={{ fontSize: 11, color: '#9898b0', marginTop: 6 }}>{subtitle}</div>
          )}
        </div>
        {icon && (
          <div style={{ fontSize: 28, opacity: 0.15, color }}>{icon}</div>
        )}
      </div>
    </Card>
  )
}
