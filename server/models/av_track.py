"""字幕与音频混音工作台的持久化模型。

三张表都遵循 ShotVersion 的约定：String 主键（UUID hex）、全部列带默认值、
不建外键（避免 SQLite 在存量库上重建表），归属校验由 API 层把 project_id
绑进查询条件完成。轨道/字幕条目的任何修改都会推进 projects.av_config_version，
渲染任务据此把配置已过期的成片判定为失效。
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text

from .base import Base


class SubtitleTrack(Base):
    """一条字幕轨：样式 + 是否烧录。字幕内容存 SubtitleCue。"""

    __tablename__ = "subtitle_tracks"
    __table_args__ = (Index("ix_subtitle_tracks_project", "project_id"),)

    id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False, index=True)
    name = Column(String, default="主字幕")
    language = Column(String, default="zh")
    # True = 烧录进画面（ASS + subtitles 滤镜）；False = 独立软字幕轨（mov_text）。
    burn_in = Column(Boolean, default=True)
    enabled = Column(Boolean, default=True)
    # 样式字段。font_size / safe_margin 以画面短边 1080 像素为基准，渲染时按实际分辨率缩放。
    font_family = Column(String, default="sans-serif")
    font_size = Column(Integer, default=54)
    primary_color = Column(String, default="#FFFFFF")
    outline_color = Column(String, default="#000000")
    outline_width = Column(Integer, default=3)
    bold = Column(Boolean, default=False)
    position = Column(String, default="bottom")  # top / middle / bottom
    safe_margin = Column(Integer, default=54)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SubtitleCue(Base):
    """一条字幕：起止毫秒 + 文本 + 角色。按 (track_id, order_index) 排序。"""

    __tablename__ = "subtitle_cues"
    __table_args__ = (
        Index("ix_subtitle_cues_track_order", "track_id", "order_index"),
        Index("ix_subtitle_cues_project", "project_id"),
    )

    id = Column(String, primary_key=True)
    track_id = Column(String, nullable=False)
    project_id = Column(String, nullable=False)
    order_index = Column(Integer, default=0)
    start_ms = Column(Integer, default=0)
    end_ms = Column(Integer, default=0)
    text = Column(Text, default="")
    character_name = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class AudioTrack(Base):
    """时间线上的一条音轨。

    kind:
    - dialogue: 绑定镜头（shot_id），素材为该镜头的 TTS 配音；渲染时该镜头
      的视频片段不再内嵌配音，改由本轨在镜头时间区间播放，从而支持音量、
      延迟、淡入淡出等调整。native 音轨镜头无法拆出对白，此类绑定无效。
    - music / ambient / sfx: 上传素材（source_path），在 start_ms 处进入混音，
      支持裁剪、循环、声像与对白 Ducking。
    """

    __tablename__ = "audio_tracks"
    __table_args__ = (Index("ix_audio_tracks_project_kind", "project_id", "kind"),)

    id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False, index=True)
    kind = Column(String, default="music")  # dialogue / music / ambient / sfx
    name = Column(String, default="")
    # 上传素材的绝对路径（经 existing_file 校验，必须位于允许的媒体根内）。
    source_path = Column(String, default="")
    source_duration_ms = Column(Integer, default=0)
    # dialogue 轨绑定镜头；其余轨道 shot_id 恒为空。
    shot_id = Column(String, default="")
    # 时间线起点（毫秒）。dialogue 轨起点由镜头区间派生，此字段被忽略。
    start_ms = Column(Integer, default=0)
    volume = Column(Float, default=1.0)  # 线性增益 0~2
    pan = Column(Float, default=0.0)  # -1 全左 ~ +1 全右
    fade_in_ms = Column(Integer, default=0)
    fade_out_ms = Column(Integer, default=0)
    delay_ms = Column(Integer, default=0)
    trim_start_ms = Column(Integer, default=0)
    trim_end_ms = Column(Integer, default=0)
    loop = Column(Boolean, default=False)
    muted = Column(Boolean, default=False)
    # 对白 Ducking：对白出现时按 duck_amount_db 压低本轨。
    duck_amount_db = Column(Float, default=0.0)  # 0 = 不 duck；负值如 -12
    duck_attack_ms = Column(Integer, default=120)
    duck_release_ms = Column(Integer, default=480)
    order_index = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
