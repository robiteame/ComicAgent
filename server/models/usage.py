from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text, UniqueConstraint

from .base import Base
from .pricing import DEFAULT_CURRENCY


class UsageRecord(Base):
    """一次真实供应商调用的用量与费用（实际值，永远不与估算混存）。

    设计约束：

    - usage_key 唯一：一次调用只允许入账一次，重试/重复回调不会重复计费；
    - 失败与取消的调用同样落库（status = failed / cancelled），保证「任务失败后
      仍能查询已发生的调用成本」；
    - cost_known=False 时 cost_micro 必须为 NULL —— 未知就是未知，不写 0；
    - 不保存供应商原始响应、API Key、本地绝对路径。
    """

    __tablename__ = "usage_records"
    __table_args__ = (
        UniqueConstraint("usage_key", name="uq_usage_records_key"),
        Index("ix_usage_records_project_created", "project_id", "created_at"),
        Index("ix_usage_records_series_created", "series_id", "created_at"),
        Index("ix_usage_records_job", "job_id"),
        Index("ix_usage_records_job_key", "job_key"),
        Index("ix_usage_records_shot_created", "shot_id", "created_at"),
        Index("ix_usage_records_capability_created", "capability", "created_at"),
        Index("ix_usage_records_job_type", "job_type"),
    )

    id = Column(String, primary_key=True)
    # 幂等键：<job_key>:<capability>:<序列/uuid> 或调用方给出的稳定去重键。
    usage_key = Column(String, nullable=False)
    job_key = Column(String, nullable=False, default="")
    job_id = Column(String, nullable=False, default="")
    job_type = Column(String, nullable=False, default="")
    # 归属任务被终结时的状态（completed / failed / cancelled / interrupted）。
    job_status = Column(String, nullable=False, default="")

    project_id = Column(String, nullable=False, default="")
    # 剧集项目的父系列；统计「按项目/剧集」时不必再做额外查询。
    series_id = Column(String, nullable=False, default="")
    shot_id = Column(String, nullable=False, default="")

    # llm / image / video / tts / ffmpeg
    capability = Column(String, nullable=False)
    provider = Column(String, nullable=False, default="")
    model = Column(String, nullable=False, default="")

    # 计价数量（整数）：llm=输入 token，image=张数，video=秒，tts=字符，ffmpeg=秒。
    quantity = Column(Integer, nullable=False, default=0)
    # 次级数量：llm=输出 token，其余为 0。
    secondary_quantity = Column(Integer, nullable=False, default=0)
    resolution = Column(String, nullable=False, default="")
    # 明细（input_tokens / output_tokens / images / seconds / characters / audio_seconds ...）
    units = Column(Text, nullable=False, default="{}")

    # 单次调用自身的结局：succeeded / failed / cancelled
    status = Column(String, nullable=False, default="succeeded")
    error_code = Column(String, nullable=False, default="")

    cost_micro = Column(Integer, nullable=True)
    currency = Column(String, nullable=False, default=DEFAULT_CURRENCY)
    cost_known = Column(Boolean, nullable=False, default=False)
    # pricing=按价目表算出；local=本地零成本能力；unknown=没有可用价目
    cost_source = Column(String, nullable=False, default="unknown")
    # 计费快照：当时用的单价 / 倍率 / 单位，便于事后复核（不含任何密钥）。
    price_snapshot = Column(Text, nullable=False, default="{}")

    # 供应商调用耗时（毫秒），与任务总时长分开记录。
    duration_ms = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class CostEstimate(Base):
    """任务启动前给出的成本/耗时估算（与 UsageRecord 分表存储，绝不混用）。

    每个任务幂等键只保留一条估算；重试会覆盖为最新一次抢占时的估算，但历史实际
    用量仍完整保存在 usage_records。
    """

    __tablename__ = "cost_estimates"
    __table_args__ = (
        UniqueConstraint("estimate_key", name="uq_cost_estimates_key"),
        Index("ix_cost_estimates_project_created", "project_id", "created_at"),
        Index("ix_cost_estimates_job", "job_id"),
    )

    id = Column(String, primary_key=True)
    estimate_key = Column(String, nullable=False)
    job_key = Column(String, nullable=False, default="")
    job_id = Column(String, nullable=False, default="")
    job_type = Column(String, nullable=False, default="")
    project_id = Column(String, nullable=False, default="")
    series_id = Column(String, nullable=False, default="")
    shot_id = Column(String, nullable=False, default="")

    currency = Column(String, nullable=False, default=DEFAULT_CURRENCY)
    estimated_cost_micro = Column(Integer, nullable=True)
    cost_known = Column(Boolean, nullable=False, default=False)
    estimated_seconds = Column(Integer, nullable=True)
    # history=按同类任务历史耗时中位数；heuristic=按单位耗时模型推算；unknown=无法估算
    duration_source = Column(String, nullable=False, default="unknown")
    # 逐能力拆解：[{capability, provider, model, quantity, cost_micro, cost_known, ...}]
    components = Column(Text, nullable=False, default="[]")
    unknown_components = Column(Text, nullable=False, default="[]")
    note = Column(String, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
