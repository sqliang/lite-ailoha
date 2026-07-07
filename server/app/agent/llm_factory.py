"""
统一 ChatOpenAI 工厂函数。

============================== 为什么需要工厂函数？ ==============================

Shell 环境中可能设置了 ALL_PROXY / all_proxy 等代理变量
(ClashX / V2Ray 等工具会自动注入)。httpx 库默认读取这些变量，
导致所有 OpenAI API 调用尝试走 SOCKS5 代理。

如果 venv 中未安装 socksio 包，会直接抛 ImportError。

============================== 解决方案 ==============================

本模块创建 ChatOpenAI 时显式传入禁用代理的 httpx 客户端，
同时设置 trust_env=False，确保不会读取系统代理环境变量。

============================== 使用方式 ==============================

    from app.agent.llm_factory import create_chat_openai
    llm = create_chat_openai(model="gpt-4o", api_key="...", base_url="...")
"""

from langchain_openai import ChatOpenAI

# 模块级全局异步客户端（线程安全，复用连接池）
# proxy=None + trust_env=False 确保不走系统代理
_async_client = None


def _get_async_client():
    """延迟导入 httpx，避免在不需要时引入依赖。"""
    global _async_client
    if _async_client is None:
        import httpx
        _async_client = httpx.AsyncClient(proxy=None, trust_env=False)
    return _async_client


def create_chat_openai(
    model: str,
    api_key: str | None,
    base_url: str | None,
    temperature: float = 0.3,
) -> ChatOpenAI:
    """
    创建 ChatOpenAI 实例，显式禁用代理。

    参数与 ChatOpenAI 一致，额外处理：
    - http_async_client: 使用禁用代理的 httpx.AsyncClient
    - 过滤空字符串 api_key/base_url（转为 None，避免传空字符串给 OpenAI SDK）
    """
    return ChatOpenAI(
        model=model,
        api_key=api_key or None,
        base_url=base_url or None,
        temperature=temperature,
        http_async_client=_get_async_client(),
    )
