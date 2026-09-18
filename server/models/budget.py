from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, UniqueConstraint

from .base import Base
from .pricing import DEFAULT_CURRENCY

# 预算作用域：全局（所有项目）与单项目（大项目 / 剧集）。
SCOPE_GLOBAL = "global"
SCOPE_PROJECT = "project"
BUDGET_SCOPES = (SCOPE_GLOBAL, SCOPE_PROJECT)


class BudgetConfig(Base):
    """软/硬预算配置。金额单位同样是货币最小单位的整数倍（micro）。

    软预算：超出时提示用户，但任务照常执行；
    硬预算：超出时阻止新任务启动（HTTP 409 / error_code=budget_exceeded）。
    时长为可选的第二维度，语义与金额一致。
    """

    __tablename__ = "budget_configs"
    __table_args__ = (
        UniqueConstraint("scope_type", "scope_id", name="uq_budget_configs_scope"),
        Index("ix_budget_configs_scope", "scope_type", "scope_id"),
    )

    id = Column(String, primary_key=True)
    scope_type = Column(String, nullable=False, default=SCOPE_PROJECT)
    # 全局预算用空串，项目预算存 project_id
    scope_id = Column(String, nullable=False, default="")

    currency = Column(String, nullable=False, default=DEFAULT_CURRENCY)
    soft_cost_micro = Column(Integer, nullable=True)
    hard_cost_micro = Column(Integer, nullable=True)
    soft_seconds = Column(Integer, nullable=True)
    hard_seconds = Column(Integer, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    note = Column(String, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class BudgetReservation(Base):
    """任务启动时按估算金额预留的额度。

    并发场景下只比对「已用 + 已预留」才能保证硬预算真的拦得住：两个任务同时启动时，
    第一个任务的实际花费在结束时才可见，若不预留，第二个任务会误判为额度充足。
    reservation_key 唯一（= 任务幂等键），重复抢占不会重复预留。
    """

    __tablename__ = "budget_reservations"
    __table_args__ = (
        UniqueConstraint("reservation_key", name="uq_budget_reservations_key"),
        Index("ix_budget_reservations_status", "status"),
        Index("ix_budget_reservations_project", "project_id", "status"),
    )

    id = Column(String, primary_key=True)
    reservation_key = Column(String, nullable=False)
    job_id = Column(String, nullable=False, default="")
    job_key = Column(String, nullable=False, default="")
    job_type = Column(String, nullable=False, default="")
    project_id = Column(String, nullable=False, default="")
    series_id = Column(String, nullable=False, default="")

    currency = Column(String, nullable=False, default=DEFAULT_CURRENCY)
    estimated_cost_micro = Column(Integer, nullable=True)
    cost_known = Column(Boolean, nullable=False, default=False)
    estimated_seconds = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    released_at = Column(DateTime, nullable=True)
