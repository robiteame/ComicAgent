import os
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 项目路径
    BASE_DIR: Path = Path(__file__).parent.parent
    SERVER_DIR: Path = Path(__file__).parent
    DATA_DIR: Path = Path(__file__).parent / "data"
    OUTPUT_DIR: Path = Path(__file__).parent.parent / "output"
    ASSETS_DIR: Path = Path(__file__).parent.parent / "assets"
    PROMPTS_DIR: Path = Path(__file__).parent / "prompts"

    # LLM 配置
    LLM_PROVIDER: str = "openai"  # openai / deepseek / mimo / seeddance
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""
    OPENAI_MODEL: str = "gpt-4o"

    # Mimo (小米 MiMo, 通过硅基流动 SiliconFlow 调用)
    MIMO_API_KEY: str = ""
    MIMO_BASE_URL: str = "https://api.siliconflow.cn/v1"
    MIMO_MODEL: str = "XiaomiMiMo/MiMo-7B-RL"

    # SeedDance (字节跳动, 通过火山引擎方舟平台调用)
    SEEDDANCE_API_KEY: str = ""
    SEEDDANCE_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    SEEDDANCE_MODEL: str = "doubao-1.5-pro-32k"

    # 图像生成配置
    IMAGE_PROVIDER: str = "local"  # local / stability
    STABILITY_API_KEY: str = ""
    STABILITY_API_URL: str = "https://api.stability.ai/v2beta"
    SD_LOCAL_URL: str = "http://127.0.0.1:7860"

    # TTS 配置
    TTS_PROVIDER: str = "edge"  # edge / cosyvoice
    TTS_DEFAULT_VOICE: str = "zh-CN-XiaoyiNeural"

    # ChromaDB 配置
    CHROMADB_PATH: str = str(Path(__file__).parent / "data" / "chromadb")

    # 数据库配置
    DATABASE_URL: str = f"sqlite:///{Path(__file__).parent / 'data' / 'comic_agent.db'}"

    # LangGraph 配置
    CHECKPOINT_PATH: str = str(Path(__file__).parent / "data" / "checkpoints")

    # 渲染配置
    DEFAULT_FPS: int = 24
    DEFAULT_RESOLUTION: str = "1080p"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
