import { Progress, Tooltip } from 'antd'

interface Props {
  score: number // 0~1
  size?: 'small' | 'normal'
}

export default function ScoreBadge({ score, size = 'normal' }: Props) {
  const pct = Math.round(score * 100)
  const color = pct >= 85 ? '#00B4D8' : pct >= 70 ? '#52c41a' : pct >= 55 ? '#fa8c16' : '#9898b0'
  const dim = size === 'small' ? 52 : 64
  const strokeWidth = size === 'small' ? 6 : 7

  return (
    <Tooltip title={`匹配度 ${pct}%`}>
      <div style={{ textAlign: 'center', width: dim }}>
        <Progress
          type="circle"
          percent={pct}
          size={dim}
          strokeColor={color}
          trailColor="rgba(255,255,255,0.06)"
          strokeWidth={strokeWidth}
          format={p => (
            <span style={{ fontSize: size === 'small' ? 12 : 14, fontWeight: 600, color }}>
              {p}%
            </span>
          )}
        />
      </div>
    </Tooltip>
  )
}
