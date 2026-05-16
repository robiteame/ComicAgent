import React from 'react'
import { useShotStore } from '../stores/shotStore'

const BottomBar: React.FC = () => {
  const { isGenerating, progress, shots } = useShotStore()

  const totalDuration = shots.reduce((sum, s) => sum + s.duration, 0)
  const remaining = isGenerating ? Math.max(0, Math.round((100 - progress) * 1.2)) : 0
  const minutes = Math.floor(remaining / 60)
  const seconds = remaining % 60

  return (
    <div style={{
      height: 32,
      background: 'var(--bg)',
      borderTop: '1px solid var(--border)',
      display: 'flex',
      alignItems: 'center',
      padding: '0 20px',
      color: 'var(--text-secondary)',
      gap: 16,
      fontSize: 12,
      flexShrink: 0,
    }}>
      <span>任务进度</span>
      <div style={{
        flex: 1,
        height: 4,
        background: 'var(--border)',
        borderRadius: 2,
        overflow: 'hidden',
        maxWidth: 240,
      }}>
        <div style={{
          width: `${isGenerating ? progress : shots.length > 0 ? 100 : 0}%`,
          height: '100%',
          background: 'var(--accent)',
          borderRadius: 2,
          transition: 'width 300ms var(--ease)',
        }} />
      </div>
      <span>
        {isGenerating
          ? `剩余 ${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
          : shots.length > 0
            ? `总时长 ${totalDuration.toFixed(1)}s`
            : '就绪'
        }
      </span>
      <span>GPU {isGenerating ? '41%' : '0%'}</span>
    </div>
  )
}

export default BottomBar
