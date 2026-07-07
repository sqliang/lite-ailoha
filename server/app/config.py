"""
Application configuration via environment variables.

多模型架构配置说明:
- VISION_MODEL: Coordinator Agent 使用，必须支持多模态（看图理解聊天截图）
- LLM_MODEL: 子 Agent（Meeting/Contact/Reminder）使用，纯文本推理即可
- 两个模型可以指向同一个（如都用 GPT-4o），也可以分开
- BASE_URL 支持任意 OpenAI 兼容 API（国内模型如 Qwen-VL、GLM-4V、DeepSeek 等）

环境变量加载优先级: .env 文件 > 系统环境变量
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置，从 .env 文件和系统环境变量加载。"""

    # --- Vision Model — Coordinator Agent 使用，需要多模态 ---
    vision_model: str = "gpt-4o"
    vision_api_key: str = ""
    vision_base_url: str = "https://api.openai.com/v1"

    # --- LLM Model — 子 Agent 使用，纯文本推理 ---
    llm_model: str = "gpt-4o"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"

    # --- Database（SQLite 零配置）---
    database_url: str = "sqlite+aiosqlite:///./lite_ailoha.db"

    # --- LangSmith（可选，调试 Agent 链路）---
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "lite-ailoha"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
