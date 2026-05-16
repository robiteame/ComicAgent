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

  setProject: (data: Partial<ProjectState>) => void
  reset: () => void
}

export const useProjectStore = create<ProjectState>((set) => ({
  projectId: null,
  title: '未命名项目',
  genre: '',
  style: 'anime',
  status: 'draft',
  outputFormat: '9:16',
  resolution: '1080p',
  platform: 'douyin',

  setProject: (data) => set((state) => ({ ...state, ...data })),
  reset: () =>
    set({
      projectId: null,
      title: '未命名项目',
      genre: '',
      style: 'anime',
      status: 'draft',
      outputFormat: '9:16',
      resolution: '1080p',
      platform: 'douyin',
    }),
}))
