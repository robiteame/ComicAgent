from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.orm import relationship
from .base import Base


class Character(Base):
    __tablename__ = "characters"

    id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    appearance = Column(Text, default="")  # JSON: 外貌详细描述
    personality = Column(Text, default="")
    visual_prompt = Column(Text, default="")  # 英文 AI 绘画 prompt
    negative_prompt = Column(Text, default="")
    voice_id = Column(String, default="")  # TTS 音色标识
    emotion_variants = Column(Text, default="{}")  # JSON: 情绪变体 prompt
    key_features = Column(Text, default="[]")  # JSON: 关键视觉特征列表
    default_outfit = Column(Text, default="")
    reference_images = Column(Text, default="[]")  # JSON: 参考图路径列表
    seed = Column(String, default="42")  # 固定 seed 保证一致性
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="characters")
