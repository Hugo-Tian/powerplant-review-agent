interface Props {
  online: boolean
}

export default function StatusDot({ online }: Props) {
  const color = online ? '#52c41a' : '#ff4d4f'
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color }}>
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: '50%',
          background: color,
          display: 'inline-block',
          boxShadow: `0 0 6px ${color}`,
          animation: online ? 'pulse 2s infinite' : 'none',
        }}
      />
      {online ? '在线' : '离线'}
      <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}`}</style>
    </span>
  )
}
