import React, { useEffect, useState, useCallback, useMemo } from 'react'
import {
  ReactFlow,
  Background,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeTypes,
  type EdgeTypes,
  MarkerType,
  getStraightPath,
  BaseEdge,
  type EdgeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Modal } from 'antd'
import { ExpandOutlined, CompressOutlined } from '@ant-design/icons'
import { useShotStore } from '../stores/shotStore'
import FlowGraphNode, { type FlowNodeData, type NodeStatus } from './FlowGraphNode'

interface GraphNodeDef {
  id: string
  label: string
  type: string
  description: string
}

interface GraphEdgeDef {
  source: string
  target: string
  label: string
}

interface GraphStructure {
  nodes: GraphNodeDef[]
  edges: GraphEdgeDef[]
}

// 节点在流水线中的顺序（用于判断完成/进行中/等待）
const PIPELINE_ORDER = [
  'start',
  'parse_script',
  'generate_storyboard',
  'generate_images',
  'generate_voice',
  'compose_video',
  'quality_check',
]

// 侧边栏紧凑布局坐标
const COMPACT_LAYOUT: Record<string, { x: number; y: number }> = {
  start: { x: 80, y: 10 },
  parse_script: { x: 80, y: 60 },
  generate_storyboard: { x: 80, y: 110 },
  generate_images: { x: 80, y: 160 },
  generate_voice: { x: 80, y: 210 },
  compose_video: { x: 80, y: 260 },
  quality_check: { x: 80, y: 310 },
  end: { x: 80, y: 400 },
  human_review: { x: 200, y: 310 },
  shot_regeneration: { x: 200, y: 360 },
}

// 弹窗大布局坐标
const EXPANDED_LAYOUT: Record<string, { x: number; y: number }> = {
  start: { x: 250, y: 20 },
  parse_script: { x: 250, y: 100 },
  generate_storyboard: { x: 250, y: 180 },
  generate_images: { x: 250, y: 260 },
  generate_voice: { x: 250, y: 340 },
  compose_video: { x: 250, y: 420 },
  quality_check: { x: 250, y: 500 },
  end: { x: 250, y: 630 },
  human_review: { x: 480, y: 500 },
  shot_regeneration: { x: 480, y: 570 },
}

// 条件边样式
const CONDITIONAL_EDGE_IDS = new Set([
  'quality_check->end',
  'quality_check->shot_regeneration',
  'quality_check->human_review',
  'human_review->compose_video',
  'shot_regeneration->quality_check',
])

function getNodeStatus(nodeId: string, currentStep: string, isGenerating: boolean): NodeStatus {
  if (nodeId === 'start') {
    return isGenerating || currentStep ? 'done' : 'pending'
  }
  if (nodeId === 'end') {
    if (!isGenerating && currentStep) return 'done'
    return 'pending'
  }
  if (!isGenerating && !currentStep) return 'pending'

  const currentIdx = PIPELINE_ORDER.indexOf(currentStep)
  const nodeIdx = PIPELINE_ORDER.indexOf(nodeId)

  // 非主流程节点（human_review, shot_regeneration）
  if (nodeIdx === -1) {
    if (currentStep === nodeId) return 'running'
    return 'pending'
  }

  if (nodeIdx < currentIdx) return 'done'
  if (nodeIdx === currentIdx) return 'running'
  return 'pending'
}

// 自定义条件边：带标签的弧线
function ConditionEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  data,
  style,
  markerEnd,
}: EdgeProps) {
  const [edgePath] = getStraightPath({ sourceX, sourceY, targetX, targetY })
  const label = (data as { label?: string })?.label

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          ...style,
          strokeDasharray: '4 3',
        }}
        markerEnd={markerEnd}
      />
      {label && (
        <text
          x={(sourceX + targetX) / 2 + 6}
          y={(sourceY + targetY) / 2}
          style={{
            fontSize: 9,
            fill: 'var(--text-tertiary)',
            fontFamily: 'var(--font)',
          }}
        >
          {label}
        </text>
      )}
    </>
  )
}

const edgeTypes: EdgeTypes = {
  condition: ConditionEdge,
}

interface FlowGraphProps {
  compact?: boolean
}

const FlowGraph: React.FC<FlowGraphProps> = ({ compact = true }) => {
  const { isGenerating, currentStep } = useShotStore()
  const [graphDef, setGraphDef] = useState<GraphStructure | null>(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    fetch('http://localhost:8000/api/graph/structure')
      .then((r) => r.json())
      .then(setGraphDef)
      .catch(() => {
        // 回退：硬编码图结构
        setGraphDef({
          nodes: [
            { id: 'start', label: '开始', type: 'input', description: '' },
            { id: 'parse_script', label: '剧本解析', type: 'process', description: '' },
            { id: 'generate_storyboard', label: '分镜拆解', type: 'process', description: '' },
            { id: 'generate_images', label: '画面渲染', type: 'process', description: '' },
            { id: 'generate_voice', label: '配音合成', type: 'process', description: '' },
            { id: 'compose_video', label: '视频合成', type: 'process', description: '' },
            { id: 'quality_check', label: '质量校验', type: 'condition', description: '' },
            { id: 'human_review', label: '人工审核', type: 'process', description: '' },
            { id: 'shot_regeneration', label: '镜头重生成', type: 'process', description: '' },
            { id: 'end', label: '完成', type: 'output', description: '' },
          ],
          edges: [
            { source: 'start', target: 'parse_script', label: '' },
            { source: 'parse_script', target: 'generate_storyboard', label: '' },
            { source: 'generate_storyboard', target: 'generate_images', label: '' },
            { source: 'generate_images', target: 'generate_voice', label: '' },
            { source: 'generate_voice', target: 'compose_video', label: '' },
            { source: 'compose_video', target: 'quality_check', label: '' },
            { source: 'quality_check', target: 'end', label: '通过' },
            { source: 'quality_check', target: 'shot_regeneration', label: '镜头失败' },
            { source: 'quality_check', target: 'human_review', label: '需审核' },
            { source: 'human_review', target: 'compose_video', label: '反馈完成' },
            { source: 'shot_regeneration', target: 'quality_check', label: '重新校验' },
          ],
        })
      })
  }, [])

  const buildFlowElements = useCallback(
    (isExpanded: boolean) => {
      if (!graphDef) return { nodes: [], edges: [] }

      const layout = isExpanded ? EXPANDED_LAYOUT : COMPACT_LAYOUT

      const nodes: Node<FlowNodeData>[] = graphDef.nodes.map((n) => ({
        id: n.id,
        position: layout[n.id] || { x: 0, y: 0 },
        type: 'flowGraphNode',
        data: {
          label: n.label,
          description: n.description,
          nodeType: n.type as FlowNodeData['nodeType'],
          status: getNodeStatus(n.id, currentStep, isGenerating),
        },
      }))

      const edges: Edge[] = graphDef.edges.map((e, i) => {
        const edgeId = `${e.source}->${e.target}`
        const isConditional = CONDITIONAL_EDGE_IDS.has(edgeId)
        const targetNode = graphDef.nodes.find((n) => n.id === e.target)
        const isLoop = e.source === 'human_review' || e.source === 'shot_regeneration'

        return {
          id: edgeId || `edge-${i}`,
          source: e.source,
          target: e.target,
          type: isConditional ? 'condition' : 'default',
          animated: isLoop,
          data: { label: e.label },
          style: {
            stroke: isConditional ? 'var(--text-tertiary)' : 'var(--border)',
            strokeWidth: 1.2,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 8,
            height: 8,
            color: isConditional ? 'var(--text-tertiary)' : 'var(--border)',
          },
        }
      })

      return { nodes, edges }
    },
    [graphDef, currentStep, isGenerating],
  )

  const nodeTypes: NodeTypes = useMemo(
    () => ({ flowGraphNode: FlowGraphNode }),
    [],
  )

  // 侧边栏紧凑视图
  if (compact && !expanded) {
    const { nodes, edges } = buildFlowElements(false)

    return (
      <div>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 10,
          }}
        >
          <div className="section-title" style={{ margin: 0 }}>
            Agent 执行流程
          </div>
          <ExpandOutlined
            style={{
              fontSize: 12,
              color: 'var(--text-tertiary)',
              cursor: 'pointer',
              transition: 'color 150ms',
            }}
            onClick={() => setExpanded(true)}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = 'var(--accent)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'var(--text-tertiary)'
            }}
          />
        </div>
        <div
          style={{
            height: 420,
            background: 'var(--bg-canvas)',
            borderRadius: 'var(--radius)',
            border: '1px solid var(--border-light)',
            overflow: 'hidden',
          }}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            zoomOnScroll={false}
            zoomOnPinch={false}
            panOnScroll={false}
            panOnDrag={false}
            fitView
            fitViewOptions={{ padding: 0.15 }}
            proOptions={{ hideAttribution: true }}
          />
        </div>
      </div>
    )
  }

  // 弹窗大视图
  const { nodes, edges } = buildFlowElements(true)

  return (
    <Modal
      title={
        <span style={{ fontSize: 13, fontWeight: 500 }}>
          LangGraph 流水线拓扑
        </span>
      }
      open={expanded}
      onCancel={() => setExpanded(false)}
      footer={null}
      width={700}
      styles={{
        body: { padding: 0, height: 680 },
        header: { padding: '12px 16px' },
      }}
      destroyOnClose
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll
        zoomOnPinch
        panOnScroll
        panOnDrag
        fitView
        fitViewOptions={{ padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
      >
        <Background
          gap={20}
          size={1}
          color="var(--border-light)"
        />
      </ReactFlow>
    </Modal>
  )
}

export default FlowGraph
