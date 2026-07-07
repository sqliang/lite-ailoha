"""
统一 ChatOpenAI 工厂 + 模块级单例管理。

============================== 为什么需要工厂函数？ ==============================

Shell 环境中可能设置了 ALL_PROXY / all_proxy 等代理变量
(ClashX / V2Ray 等工具会自动注入)。httpx 库默认读取这些变量，
导致所有 OpenAI API 调用尝试走 SOCKS5 代理。

如果 venv 中未安装 socksio 包，会直接抛 ImportError。

============================== 解决方案 ==============================

本模块创建 ChatOpenAI 时显式传入禁用代理的 httpx 客户端，
同时设置 trust_env=False，确保不会读取系统代理环境变量。

============================== LLM 实例管理 ==============================

两个模块级单例:
  - get_vision_llm()  — VISION_MODEL（豆包）：仅 structure_conversation 工具内部使用
  - get_text_llm()    — LLM_MODEL（DeepSeek）：Coordinator + 子Agent + 洞察 共用

使用者:
  deep_agent.py      — get_text_llm() → Coordinator 的大脑
  subagents/         — get_text_llm() → 注入给 meeting/contact/reminder
  tools/structure.py — get_vision_llm() → 看图
  api/sessions.py    — get_text_llm() → 阶段二生成的洞察
"""

from langchain_openai import ChatOpenAI
from app.config import settings

# =============================================================================
# 共享 httpx 客户端（禁用代理，复用连接池）
# =============================================================================

_async_client = None


def _get_async_client():
    """延迟导入 httpx，避免在不需要时引入依赖。"""
    global _async_client
    if _async_client is None:
        import httpx
        _async_client = httpx.AsyncClient(proxy=None, trust_env=False)
    return _async_client


# =============================================================================
# 内部工厂（不对外暴露，外部用单例函数）
# =============================================================================

def create_chat_openai(
    model: str,
    api_key: str | None,
    base_url: str | None,
    temperature: float = 0.3,
) -> ChatOpenAI:
    """创建 ChatOpenAI 实例，显式禁用代理。"""
    return ChatOpenAI(
        model=model,
        api_key=api_key or None,
        base_url=base_url or None,
        temperature=temperature,
        http_async_client=_get_async_client(),
    )


# =============================================================================
# LLM 单例 — 全局复用，避免重复创建
# =============================================================================

_vision_llm = None
_text_llm = None


def get_vision_llm() -> ChatOpenAI:
    """
    VISION_MODEL 单例。

    用途: structure_conversation 工具内部看图。
    模型: 豆包 doubao-seed-evolving（多模态）。
    """
    global _vision_llm
    if _vision_llm is None:
        _vision_llm = create_chat_openai(
            model=settings.vision_model,
            api_key=settings.vision_api_key,
            base_url=settings.vision_base_url,
        )
    return _vision_llm


def get_text_llm() -> ChatOpenAI:
    """
    LLM_MODEL 单例。

    用途: Coordinator（大脑）+ 子Agent（meeting/contact/reminder）+ 洞察生成。
    模型: DeepSeek deepseek-v4-pro（纯文本推理）。
    """
    global _text_llm
    if _text_llm is None:
        _text_llm = create_chat_openai(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
    return _text_llm
