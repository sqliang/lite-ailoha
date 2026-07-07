"""
Application configuration via environment variables.

多模型架构配置说明:
- VISION_MODEL: Coordinator Agent 使用，必须支持多模态（看图理解聊天截图）
- LLM_MODEL: 子 Agent（Meeting/Contact/Reminder）使用，纯文本推理即可
- 两个模型可以指向同一个（如都用 GPT-4o），也可以分开
- BASE_URL 支持任意 OpenAI 兼容 API（国内模型如 Qwen-VL、GLM-4V、DeepSeek 等）

环境变量加载优先级: .env 文件 > 系统环境变量

============================== 使用方式 ==============================

    from app.config import settings
    llm = ChatOpenAI(
        model=settings.vision_model,
        api_key=settings.vision_api_key,
        base_url=settings.vision_base_url,
    )

============================== 引用位置 ==============================

    deep_agent.py   — vision_model/api_key/base_url, llm_model/api_key/base_url
    structure.py    — vision_model/api_key/base_url
    subagents.py    — llm_model/api_key/base_url
    database.py     — database_url → 解析 SQLite 路径
    checkpoint.py   — database_url → 解析 SQLite 路径
"""
from pydantic_settings import BaseSettings


# =============================================================================
# 以下是之前兼容 LangSmith 的代码，因 pydantic-settings 不会把 .env 的
# 值注入 os.environ，导致 helper 函数读取不到 .env 中的 LANGSMITH_* 变量。
# 已被 main.py 中的手动 .env 加载逻辑替代，暂时注释保留。
# =============================================================================

# import os
#
# def _get_langsmith_api_key() -> str:
#     return os.environ.get("LANGCHAIN_API_KEY", "") or os.environ.get("LANGSMITH_API_KEY", "")
#
# def _get_langsmith_project() -> str:
#     return os.environ.get("LANGCHAIN_PROJECT", "") or os.environ.get("LANGSMITH_PROJECT", "lite-ailoha")
#
# def _get_langsmith_endpoint() -> str:
#     return os.environ.get("LANGCHAIN_ENDPOINT", "") or os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")


class Settings(BaseSettings):
    """应用配置，从 .env 文件和系统环境变量加载。"""

    # --- Vision Model — Coordinator Agent 使用，需要多模态 ---
    vision_model: str = "doubao-seed-evolving"
    vision_api_key: str = ""
    vision_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"

    # --- LLM Model — 子 Agent 使用，纯文本推理 ---
    llm_model: str = "deepseek-v4-pro"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"

    # --- Database（SQLite 零配置）---
    database_url: str = "sqlite+aiosqlite:///./lite_ailoha.db"

    # --- LangSmith（已废弃，由 main.py 手动加载 .env 处理）---
    # langchain_tracing_v2: bool = False
    # langchain_api_key: str = ""
    # langchain_project: str = "lite-ailoha"
    # langsmith_endpoint: str = "https://api.smith.langchain.com"

    # --- 以下 __init__ 已废弃：pydantic-settings 不会把 .env 注入 os.environ，
    #     导致 helper 函数读取到的始终是空值。LangSmith 配置已由 main.py 处理。---
    # def __init__(self, **kwargs):
    #     super().__init__(**kwargs)
    #     if not self.langchain_api_key:
    #         self.langchain_api_key = _get_langsmith_api_key()
    #     if not self.langchain_project or self.langchain_project == "lite-ailoha":
    #         self.langchain_project = _get_langsmith_project()
    #     if not self.langsmith_endpoint or self.langsmith_endpoint == "https://api.smith.langchain.com":
    #         self.langsmith_endpoint = _get_langsmith_endpoint()

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "allow"}


settings = Settings()
