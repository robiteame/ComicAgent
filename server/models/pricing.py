from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text, UniqueConstraint

from .base import Base

# 金额一律用「货币最小单位的整数倍」表示，绝不使用浮点。
#
# 本项目的记账精度取 10^-6 个货币单位（micro），1 CNY = 1_000_000 micro。
# 之所以比「分」更细，是因为单次 LLM 调用常常远低于 1 分钱，用分记账会把大量
# 调用舍入成 0；用整数 micro 既保留精度，又保证任何一步计算都不引入浮点误差。
MICRO_PER_UNIT = 1_000_000
DEFAULT_CURRENCY = "CNY"


class PricingConfig(Base):
    """某一能力（LLM / 图像 / 视频 / TTS / FFmpeg）的计价配置。

    一行 = 一个可匹配的价目：(capability, provider, model)，其中 model 为空表示
    「该 provider 下所有模型的通用价」，provider 为空表示「该能力的兜底价」。匹配
    优先级从具体到宽泛：model 精确 > provider 通用 > 能力兜底。

    configured=False 表示这一行只是占位模板（前端展示用），其价格不参与计费：
    未配置价格的调用一律记为「成本未知」，绝不按 0 元或猜测价格入账。
    """

    __tablename__ = "pricing_configs"
    __table_args__ = (
        UniqueConstraint("capability", "provider", "model", name="uq_pricing_configs_scope"),
        Index("ix_pricing_configs_capability", "capability"),
    )

    id = Column(String, primary_key=True)
    # llm / image / video / tts / ffmpeg
    capability = Column(String, nullable=False)
    # 协议名（ark-seedream / ark-seedance / mimo-tts / openai-chat / placeholder / local ...）
    provider = Column(String, nullable=False, default="")
    # 模型名；空串代表该 provider 的通用价
    model = Column(String, nullable=False, default="")

    currency = Column(String, nullable=False, default=DEFAULT_CURRENCY)
    # 主计价单位的单价（micro）：llm=每 1M 输入 token，image=每张，video=每秒，
    # tts=每 1K 字符，ffmpeg=每分钟编码。
    unit_price_micro = Column(Integer, nullable=True)
    # 次级计价单位单价（micro），目前仅 LLM 使用（每 1M 输出 token）。
    unit_price_secondary_micro = Column(Integer, nullable=True)
    # 分辨率/画质倍率（micro，1_000_000 = 1.0）。整数倍率，避免浮点乘法。
    resolution_multipliers = Column(Text, nullable=False, default="{}")
    configured = Column(Boolean, nullable=False, default=False)
    note = Column(String, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
