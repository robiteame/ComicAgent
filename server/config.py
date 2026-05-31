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
    LLM_MAX_TOKENS: int = 4096

    # Mimo (小米 MiMo, 通过硅基流动 SiliconFlow 调用)
    MIMO_API_KEY: str = ""
    MIMO_BASE_URL: str = "https://token-plan-cn.xiaomimimo.com/v1"
    MIMO_MODEL: str = "mimo-v2.5"
    MIMO_MULTIMODAL_MODEL: str = "mimo-v2-omni"
    MIMO_TTS_MODEL: str = "mimo-v2.5-tts"
    MIMO_TTS_VOICE: str = "冰糖"
    MIMO_TTS_FORMAT: str = "wav"

    # SeedDance / Seedream (字节跳动, 通过火山引擎方舟平台调用)
    ARK_API_KEY: str = ""
    SEEDDANCE_API_KEY: str = ""
    SEEDREAM_API_KEY: str = ""
    SEEDDANCE_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    SEEDDANCE_MODEL: str = "doubao-seedance-1-5-pro-251215"
    VIDEO_PROVIDER: str = "Doubao-Seedance-1.5-pro"
    SEEDREAM_MODEL: str = "doubao-seedream-5.0-lite"
    SEEDREAM_IMAGE_SIZE: str = "1440x2560"

    # 图像生成配置
    IMAGE_PROVIDER: str = "local"  # local / stability / doubao-seedream-5.0-lite
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
        env_file = (
            str(Path(__file__).parent / ".env"),
            str(Path(__file__).parent.parent / ".env"),
        )
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
