import React, { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'

export type NodeStatus = 'pending' | 'running' | 'done' | 'error'

export interface FlowNodeData {
  label: string
  description: string
  nodeType: 'input' | 'output' | 'process' | 'condition'
  status: NodeStatus
  [key: string]: unknown
}

const statusColors: Record<NodeStatus, string> = {
  pending: 'var(--text-quaternary)',
  running: 'var(--amber)',
  done: 'var(--green)',
  error: 'var(--red)',
}

const typeIcons: Record<string, string> = {
  input: '▶',
  output: '◼',
  process: '◆',
  condition: '◇',
}

const FlowGraphNode: React.FC<NodeProps> = ({ data, selected }) => {
  const { label, description, nodeType, status } = data as FlowNodeData
  const color = statusColors[status]
  const isRunning = status === 'running'
  const isDone = status === 'done'

  return (
    <div
      style={{
        background: 'var(--bg-white)',
        border: `1.5px solid ${selected ? 'var(--accent)' : isRunning ? 'var(--amber)' : isDone ? 'var(--green)' : 'var(--border)'}`,
        borderRadius: 'var(--radius)',
        padding: '6px 10px',
        minWidth: 90,
        maxWidth: 140,
        boxShadow: isRunning
          ? '0 0 12px rgba(255, 149, 0, 0.2)'
          : 'var(--shadow-sm)',
        transition: 'all 200ms var(--ease)',
        position: 'relative',
        cursor: 'default',
      }}
    >
      {nodeType !== 'input' && (
        <Handle
          type="target"
          position={Position.Top}
          style={{
            width: 6,
            height: 6,
            background: color,
            border: '1.5px solid var(--bg-white)',
            top: -3,
          }}
        />
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        <span style={{ fontSize: 8, color, lineHeight: 1 }}>
          {typeIcons[nodeType]}
        </span>
        <span
          style={{
            fontSize: 11,
            fontWeight: 500,
            color: 'var(--text)',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {label}
        </span>
        {isRunning && (
          <span
            style={{
              width: 5,
              height: 5,
              borderRadius: '50%',
              background: 'var(--amber)',
              animation: 'pulse 1.5s ease-in-out infinite',
              flexShrink: 0,
            }}
          />
        )}
      </div>

      {nodeType !== 'output' && (
        <Handle
          type="source"
          position={Position.Bottom}
          style={{
            width: 6,
            height: 6,
            background: color,
            border: '1.5px solid var(--bg-white)',
            bottom: -3,
          }}
        />
      )}
    </div>
  )
}

export default memo(FlowGraphNode)
