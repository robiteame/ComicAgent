import { create } from 'zustand'

export interface Shot {
  id: string
  project_id: string
  sequence: number
  shot_type: string
  scene_description: string
  character_action: string
  dialogue: string
  camera_angle: string
  duration: number
  emotion: string
  transition: string
  image_path: string
  audio_path: string
  status: string
  version: number
  characters_in_scene: string[]
}

interface ShotState {
  shots: Shot[]
  selectedShotId: string | null
  isGenerating: boolean
  progress: number
  currentStep: string

  setShots: (shots: Shot[]) => void
  updateShot: (id: string, data: Partial<Shot>) => void
  selectShot: (id: string | null) => void
  setGenerating: (v: boolean) => void
  setProgress: (progress: number, step: string) => void
  addShot: (shot: Shot) => void
  removeShot: (id: string) => void
  reorderShots: (newOrder: string[]) => void
}

export const useShotStore = create<ShotState>((set, get) => ({
  shots: [],
  selectedShotId: null,
  isGenerating: false,
  progress: 0,
  currentStep: '',

  setShots: (shots) => set({ shots }),

  updateShot: (id, data) =>
    set((state) => ({
      shots: state.shots.map((s) => (s.id === id ? { ...s, ...data } : s)),
    })),

  selectShot: (id) => set({ selectedShotId: id }),

  setGenerating: (v) => set({ isGenerating: v }),

  setProgress: (progress, step) => set({ progress, currentStep: step }),

  addShot: (shot) => set((state) => ({ shots: [...state.shots, shot] })),

  removeShot: (id) =>
    set((state) => ({ shots: state.shots.filter((s) => s.id !== id) })),

  reorderShots: (newOrder) =>
    set((state) => {
      const shotMap = new Map(state.shots.map((s) => [s.id, s]))
      const reordered = newOrder
        .map((id) => shotMap.get(id))
        .filter(Boolean) as Shot[]
      return { shots: reordered }
    }),
}))
