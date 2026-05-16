import React, { useState } from 'react'
import { Input, Button, message } from 'antd'
import { SendOutlined, UploadOutlined } from '@ant-design/icons'
import { useShotStore } from '../stores/shotStore'
import { useProjectStore } from '../stores/projectStore'
import { projectApi, scriptApi, createWebSocket } from '../services/api'

const { TextArea } = Input

const MainWorkspace: React.FC = () => {
  const { shots, selectedShotId, selectShot, setShots, setGenerating, setProgress, isGenerating } = useShotStore()
  const { setProject, style, platform, outputFormat } = useProjectStore()

  const [script, setScript] = useState('')
  const [loading, setLoading] = useState(false)

  const selectedShot = shots.find((s) => s.id === selectedShotId) || shots[0]

  const handleGenerate = async () => {
    if (!script.trim()) { message.warning('请输入剧本内容'); return }
    setLoading(true)
    setGenerating(true)
    try {
      const project = await projectApi.create({ title: script.slice(0, 20), style, genre: '' })
      setProject({ projectId: project.id, title: project.title })

      const ws = createWebSocket(project.id, (data) => {
        if (data.type === 'progress') {
          setProgress(data.progress, data.step)
        } else if (data.type === 'complete') {
          setShots(data.shots || [])
          setGenerating(false)
          setLoading(false)
          message.success('生成完成')
          ws.close()
        } else if (data.type === 'error') {
          message.error(data.message)
          setGenerating(false)
          setLoading(false)
          ws.close()
        }
      })

      await scriptApi.parse({
        project_id: project.id,
        user_input: script,
        input_type: 'text',
        style,
        output_format: outputFormat,
        platform,
        target_duration: 30,
      })
    } catch (err: any) {
      message.error('提交失败: ' + (err.message || '未知错误'))
      setGenerating(false)
      setLoading(false)
    }
  }

  const imageUrl = selectedShot?.image_path
    ? `http://localhost:8000/output/${selectedShot.image_path.replace(/.*output[/\\]/, '')}`
    : null

  return (
    <div style={{
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      padding: 16,
      gap: 12,
      overflow: 'hidden',
    }}>
      {/* 剧本面板 */}
      <div style={{
        height: '32%',
        minHeight: 160,
        background: 'var(--bg-white)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)',
        padding: 14,
        boxShadow: 'var(--shadow-sm)',
        display: 'flex',
        flexDirection: 'column',
      }}>
        <div className="section-title">剧本 / 分镜编辑</div>
        <div style={{ flex: 1, display: 'flex', gap: 10, marginTop: 6 }}>
          <TextArea
            value={script}
            onChange={(e) => setScript(e.target.value)}
            placeholder={'输入剧本内容...\n\n场景：雨夜小巷\n人物：男主 · 情绪低沉\n镜头：中景，缓慢推进，男主抬头望向远处霓虹'}
            style={{
              flex: 1,
              resize: 'none',
              fontSize: 12,
              lineHeight: 1.6,
              background: 'transparent',
              border: 'none',
              boxShadow: 'none',
            }}
          />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flexShrink: 0 }}>
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleGenerate}
              loading={loading}
              size="small"
              style={{ height: 28, fontSize: 11 }}
            >
              生成分镜
            </Button>
            <Button icon={<UploadOutlined />} size="small" style={{ height: 28, fontSize: 11 }}>
              上传
            </Button>
          </div>
        </div>
      </div>

      {/* 预览面板 */}
      <div style={{
        flex: 1,
        background: 'var(--bg-white)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        position: 'relative',
        overflow: 'hidden',
      }}>
        {/* 主预览区 */}
        <div style={{
          width: '86%',
          height: '84%',
          background: 'var(--bg-canvas)',
          borderRadius: 'var(--radius)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--text-secondary)',
          border: '1px solid var(--border)',
          overflow: 'hidden',
          position: 'relative',
        }}>
          {isGenerating ? (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 6 }}>正在生成分镜...</div>
              <div style={{
                width: 120,
                height: 3,
                background: 'var(--border)',
                borderRadius: 2,
                overflow: 'hidden',
                margin: '0 auto',
              }}>
                <div style={{
                  width: '42%',
                  height: '100%',
                  background: 'var(--accent)',
                  borderRadius: 2,
                  animation: 'shimmer 1.5s infinite',
                }} />
              </div>
            </div>
          ) : imageUrl ? (
            <img
              src={imageUrl}
              alt=""
              style={{ width: '100%', height: '100%', objectFit: 'contain' }}
            />
          ) : (
            <span style={{ fontSize: 13 }}>漫剧画面预览</span>
          )}

          {/* 镜头信息叠加层 */}
          {selectedShot && !isGenerating && (
            <div style={{
              position: 'absolute',
              bottom: 8,
              left: 8,
              right: 8,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'flex-end',
            }}>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                {selectedShot.scene_description}
              </div>
              {selectedShot.dialogue && (
                <div style={{ fontSize: 11, color: 'var(--accent)', fontStyle: 'italic', marginLeft: 12 }}>
                  "{selectedShot.dialogue}"
                </div>
              )}
            </div>
          )}
        </div>

        {/* 底部镜头缩略图条 */}
        {shots.length > 0 && (
          <div style={{
            position: 'absolute',
            bottom: 10,
            display: 'flex',
            gap: 6,
          }}>
            {shots.map((shot, i) => {
              const thumbUrl = shot.image_path
                ? `http://localhost:8000/output/${shot.image_path.replace(/.*output[/\\]/, '')}`
                : null
              const isSelected = (selectedShotId || shots[0]?.id) === shot.id
              return (
                <div
                  key={shot.id}
                  onClick={() => selectShot(shot.id)}
                  style={{
                    width: 58,
                    height: 34,
                    background: thumbUrl ? 'transparent' : 'var(--bg-canvas)',
                    borderRadius: 'var(--radius-sm)',
                    border: isSelected ? '2px solid var(--accent)' : '1px solid var(--border)',
                    overflow: 'hidden',
                    cursor: 'pointer',
                    transition: 'all 120ms var(--ease)',
                    flexShrink: 0,
                  }}
                >
                  {thumbUrl ? (
                    <img src={thumbUrl} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  ) : (
                    <div style={{
                      width: '100%',
                      height: '100%',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 10,
                      color: 'var(--text-tertiary)',
                    }}>
                      {i + 1}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export default MainWorkspace
