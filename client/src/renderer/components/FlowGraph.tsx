import React from 'react'
import { useShotStore } from '../stores/shotStore'

interface FlowGraphProps {
  compact?: boolean
}

const STEPS = [
  { id: 'generate_script', label: '剧本' },
  { id: 'parse_script', label: '解析' },
  { id: 'generate_storyboard', label: '分镜' },
  { id: 'generate_reference_images', label: '参考图' },
  { id: 'wait_storyboard_confirm', label: '确认' },
  { id: 'generate_images', label: '渲染' },
  { id: 'generate_voice', label: '音频' },
  { id: 'compose_video', label: '成片' },
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
