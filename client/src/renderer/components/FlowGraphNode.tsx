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
  pending: 'var(--gray)',
  running: 'var(--orange)',
  done: 'var(--green)',
  error: 'var(--orange)',
}

const typeLabels: Record<string, string> = {
  input: '入',
  output: '出',
  process: '处',
  condition: '判',
}

const FlowGraphNode: React.FC<NodeProps> = ({ data, selected }) => {
  const { label, nodeType, status } = data as FlowNodeData
  const color = statusColors[status]
  const isRunning = status === 'running'
  const isDone = status === 'done'

  return (
    <div
      style={{
        background: 'var(--white)',
        border: `1.5px solid ${selected ? 'var(--green)' : isRunning ? 'var(--orange)' : isDone ? 'var(--green)' : 'var(--line)'}`,
        borderRadius: '14px',
        padding: '8px 12px',
        minWidth: 98,
        maxWidth: 152,
        boxShadow: '0 1px 2px rgba(30, 33, 36, 0.05)',
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
            width: 7,
            height: 7,
            background: color,
            border: '1px solid var(--white)',
            top: -4,
          }}
        />
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
        <span
          style={{
            width: 16,
            height: 16,
            borderRadius: 6,
            border: `1px solid ${color}`,
            color,
            display: 'grid',
            placeItems: 'center',
            fontSize: 10,
            lineHeight: 1,
            background: 'rgba(127, 138, 149, 0.06)',
            fontWeight: 600,
            flexShrink: 0,
          }}
        >
          {typeLabels[nodeType]}
        </span>

        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
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
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: 'var(--orange)',
              animation: 'pulse 1.6s ease-in-out infinite',
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
            width: 7,
            height: 7,
            background: color,
            border: '1px solid var(--white)',
            bottom: -4,
          }}
        />
      )}
    </div>
  )
}

export default memo(FlowGraphNode)
