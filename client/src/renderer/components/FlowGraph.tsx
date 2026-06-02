import React from 'react'
import { useShotStore } from '../stores/shotStore'

interface FlowGraphProps {
  compact?: boolean
}

const STEPS = [
  { id: 'generate_script', label: '剧本' },
  { id: 'parse_script', label: '解析' },
  { id: 'generate_storyboard', label: '分镜' },
  { id: 'wait_asset_confirm', label: '资产' },
  { id: 'generate_storyboard_images', label: '定稿图' },
  { id: 'wait_storyboard_approval', label: '镜头审核' },
  { id: 'generate_voice', label: '配音' },
  { id: 'generate_seedance_video', label: '单镜头视频' },
  { id: 'compose_video', label: '合成' },
  { id: 'quality_check', label: '校验' },
]

function stepState(stepId: string, currentStep: string, isGenerating: boolean, hasVideo: boolean) {
  if (hasVideo) return 'done'
  const currentIndex = STEPS.findIndex((step) => step.id === currentStep)
  const stepIndex = STEPS.findIndex((step) => step.id === stepId)
  if (stepIndex < 0 || currentIndex < 0) return 'pending'
  if (stepIndex < currentIndex) return 'done'
  if (stepIndex === currentIndex) return isGenerating ? 'running' : 'done'
  return 'pending'
}

const FlowGraph: React.FC<FlowGraphProps> = () => {
  const { currentStep, isGenerating, videoPath } = useShotStore()

  return (
    <div className="flow-steps" aria-label="Agent 执行流程">
      {STEPS.map((step, index) => {
        const state = stepState(step.id, currentStep, isGenerating, Boolean(videoPath))
        return (
          <React.Fragment key={step.id}>
            <div className={`flow-step ${state}`}>
              <span className="flow-step-dot" />
              <span>{step.label}</span>
            </div>
            {index < STEPS.length - 1 && <span className={`flow-step-line ${state}`} />}
          </React.Fragment>
        )
      })}
    </div>
  )
}

export default FlowGraph
