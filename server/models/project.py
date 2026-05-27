from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.orm import relationship

from .base import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False, default="未命名项目")
    genre = Column(String, default="")
    style = Column(String, default="anime")
    status = Column(String, default="draft")
    input_text = Column(Text, default="")
    input_type = Column(String, default="text")
    output_format = Column(String, default="9:16")
    resolution = Column(String, default="1080p")
    platform = Column(String, default="douyin")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    shots = relationship("Shot", back_populates="project", cascade="all, delete-orphan")
    characters = relationship("Character", back_populates="project", cascade="all, delete-orphan")
