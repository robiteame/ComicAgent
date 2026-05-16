from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, Float, Integer
from sqlalchemy.orm import relationship
from .base import Base


class Shot(Base):
    __tablename__ = "shots"

    id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False, index=True)
    sequence = Column(Integer, default=0)
    shot_type = Column(String, default="medium")  # wide/medium/close-up/extreme_close
    scene_description = Column(Text, default="")
    character_action = Column(Text, default="")
    dialogue = Column(Text, default="")
    camera_angle = Column(String, default="正面")
    camera_movement = Column(String, default="静止")
    duration = Column(Float, default=3.0)
    emotion = Column(String, default="neutral")
    transition = Column(String, default="cut")
    image_path = Column(String, default="")
    audio_path = Column(String, default="")
    status = Column(String, default="pending")  # pending/generating/done/failed/needs_review
    version = Column(Integer, default=1)
    parent_version_id = Column(String, default="")
    characters_in_scene = Column(Text, default="[]")  # JSON array of character names
    visual_notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="shots")
