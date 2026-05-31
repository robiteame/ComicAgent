from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base


class SceneAsset(Base):
    __tablename__ = "scene_assets"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    visual_prompt = Column(Text, default="")
    negative_prompt = Column(Text, default="")
    reference_images = Column(Text, default="[]")
    key_features = Column(Text, default="[]")
    seed = Column(Integer, default=1200)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="scenes")
