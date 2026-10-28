import { Tag } from 'antd'

const CONFIG: Record<string, { color: string; bg: string }> = {
  紧急: { color: '#ff4d4f', bg: 'rgba(255,77,79,0.12)' },
  重要: { color: '#fa8c16', bg: 'rgba(250,140,22,0.12)' },
  一般: { color: '#52c41a', bg: 'rgba(82,196,26,0.12)' },
  建议: { color: '#c0c0d0', bg: 'rgba(154,154,154,0.10)' },
}

interface Props {
  level: string
}

export default function LevelTag({ level }: Props) {
  const cfg = CONFIG[level] ?? { color: '#c0c0d0', bg: 'rgba(154,154,154,0.10)' }
  return (
    <Tag
      style={{
        color: cfg.color,
        background: cfg.bg,
        border: `1px solid ${cfg.color}30`,
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
        lineHeight: '18px',
        padding: '0 6px',
      }}
    >
      {level}
    </Tag>
  )
}
