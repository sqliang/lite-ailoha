"""
Application configuration via environment variables.

多模型架构配置说明:
- VISION_MODEL: Coordinator Agent 使用，必须支持多模态（看图理解聊天截图）
- LLM_MODEL: 子 Agent（Meeting/Contact/Reminder）使用，纯文本推理即可
- 两个模型可以指向同一个（如都用 GPT-4o），也可以分开
- BASE_URL 支持任意 OpenAI 兼容 API（国内模型如 Qwen-VL、GLM-4V、DeepSeek 等）

环境变量加载优先级: .env 文件 > 系统环境变量
"""
import os
from pydantic_settings import BaseSettings


def _get_langsmith_api_key() -> str:
    """LangSmith API Key: 兼容 LANGCHAIN_API_KEY 和 LANGSMITH_API_KEY 两种写法。"""
    return os.environ.get("LANGCHAIN_API_KEY", "") or os.environ.get("LANGSMITH_API_KEY", "")


def _get_langsmith_project() -> str:
    """LangSmith Project: 兼容 LANGCHAIN_PROJECT 和 LANGSMITH_PROJECT 两种写法。"""
    return os.environ.get("LANGCHAIN_PROJECT", "") or os.environ.get("LANGSMITH_PROJECT", "lite-ailoha")


def _get_langsmith_endpoint() -> str:
    """LangSmith Endpoint: 兼容 LANGCHAIN_ENDPOINT 和 LANGSMITH_ENDPOINT 两种写法。"""
    return os.environ.get("LANGCHAIN_ENDPOINT", "") or os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")


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
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 兼容 LANGSMITH_* 和 LANGCHAIN_* 两种 env var 命名
        if not self.langchain_api_key:
            self.langchain_api_key = _get_langsmith_api_key()
        if not self.langchain_project or self.langchain_project == "lite-ailoha":
            self.langchain_project = _get_langsmith_project()
        if not self.langsmith_endpoint or self.langsmith_endpoint == "https://api.smith.langchain.com":
            self.langsmith_endpoint = _get_langsmith_endpoint()

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "allow"}


settings = Settings()
