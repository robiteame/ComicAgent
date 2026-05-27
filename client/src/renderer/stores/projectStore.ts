import { create } from 'zustand'

interface ProjectState {
  projectId: string | null
  title: string
  genre: string
  style: string
  status: string
  outputFormat: string
  resolution: string
  platform: string
  characters: any[]

  setProject: (data: Partial<ProjectState>) => void
  reset: () => void
}

const DEFAULT_PROJECT = {
  projectId: null,
  title: '未命名项目',
  genre: '',
  style: 'anime',
  status: 'draft',
  outputFormat: '9:16',
  resolution: '1080p',
  platform: 'douyin',
  characters: [],
}

export const useProjectStore = create<ProjectState>((set) => ({
  ...DEFAULT_PROJECT,

  setProject: (data) => set((state) => ({ ...state, ...data })),
  reset: () => set(DEFAULT_PROJECT),
}))
