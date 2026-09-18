from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from .base import Base


class ShotVersion(Base):
    """镜头历史的不可变快照。

    版本记录只追加：任何写路径都只 INSERT 新行，历史行不允许原地修改（SQLite
    触发器兜底，见 ``db/database.py::_ensure_shot_version_append_only``）。行的
    元数据描述「这份状态为什么被记录」，``snapshot`` 列保存当时镜头的完整字段
    快照（含媒体路径与生成 Prompt），恢复时按快照重建镜头并追加新行。
    """

    __tablename__ = "shot_versions"
    __table_args__ = (
        Index("ix_shot_versions_shot_number", "shot_id", "number"),
        Index("ix_shot_versions_project", "project_id"),
    )

    id = Column(String, primary_key=True)
    shot_id = Column(String, nullable=False)
    project_id = Column(String, nullable=False, default="")
    # 镜头时间线内的稠密序号（1,2,3...），供界面展示 v1/v2/v3。
    number = Column(Integer, nullable=False, default=1)
    # 快照时刻的 shot.version，用于与任务防覆盖机制对齐。
    version = Column(Integer, nullable=False, default=1)
    # manual_edit / regenerate / restore / import
    source = Column(String, nullable=False, default="manual_edit")
    # 触发变更的后台任务幂等键（手动编辑为空串）。
    task_id = Column(String, nullable=False, default="")
    # 链式父版本：追加该行之前的最新版本 ID，首条为空串。
    parent_version_id = Column(String, nullable=False, default="")
    # 快照内容的规范化哈希，用于追加去重与「当前是否等于历史版本」判断。
    content_hash = Column(String, nullable=False, default="")
    # 镜头字段快照 JSON（_serialize_shot 的字段集 + prompt/negative_prompt）。
    snapshot = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
