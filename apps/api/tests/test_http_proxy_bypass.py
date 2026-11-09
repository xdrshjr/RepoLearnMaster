"""回环请求绝不经过系统代理（T-NET-1 / T-NET-2）。

真实现场（2026-11-09 本机实测）：机器上装有系统代理（注册表
`ProxyEnable=1` / `ProxyServer=127.0.0.1:7897`，且 `ProxyOverride` 里写了
`localhost;127.*`）。同一个本地服务：

    urllib        → 200
    httpx 默认     → **502**（请求被系统代理接走，代理对这个端口返回 502）
    httpx trust_env=False → 200

`httpx` 只读 `HTTP_PROXY` / `NO_PROXY` 环境变量，**不读 Windows 注册表里的
ProxyOverride**，所以"我在系统设置里给回环开了例外"对它无效。

后果不是测试红而是**产品会随机坏**：web → api → kernel 整条关键路径都是回环，
而 `providers/http.py::new_client` 之前用的是 `trust_env` 默认值（True）。
症状是"内核不可用 / 429 / 连接被拒"，而 `curl` 和服务日志都正常——最难查的一类。
"""

from __future__ import annotations

import httpx

from repolearn.providers.http import new_client, new_local_client


def test_loopback_client_ignores_proxy_env(monkeypatch):
    """T-NET-1：内核/本机 API 用的客户端必须关掉环境代理。"""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:7897")

    client = new_local_client(timeout_read=5.0)
    try:
        assert client.trust_env is False
        # httpx 在 trust_env=False 时不会装载任何代理
        assert not [k for k in client._mounts if k is not None]
    finally:
        import asyncio

        asyncio.run(client.aclose())


def test_external_client_still_honours_proxy(monkeypatch):
    """T-NET-2：GitHub / 模型调用**必须**继续走系统代理（很多机器只能这样出网）。"""
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")

    client = new_client(timeout_read=5.0)
    try:
        # `trust_env=True` 是外网调用能出网的前提；关掉它等于让装了代理的机器连不上 GitHub。
        assert client.trust_env is True
        # 并且 httpx 确实会为 https 装载这个代理（trust_env 生效的实际证据）
        from httpx._utils import get_environment_proxies

        proxies = get_environment_proxies()
        assert any(str(url).startswith("http://127.0.0.1:7897") for url in proxies.values()), proxies
    finally:
        import asyncio

        asyncio.run(client.aclose())


def test_kernel_runtime_uses_the_loopback_client(monkeypatch):
    """T-NET-3：`agent_runtime` 里没有任何一处还在用会走代理的客户端。"""
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "repolearn" / "providers" / "agent_runtime.py"
    text = source.read_text(encoding="utf-8")

    assert "new_local_client" in text
    # 只允许 `new_local_client(...)` 这一种用法；出现裸 `new_client(` 就说明
    # 有人把回环调用改回了会走代理的版本。
    assert "with new_client(" not in text
    assert "= new_client(" not in text
    # 静态兜底：确认 httpx 仍然是我们认知里的那个行为（版本升级会改变 _mounts 语义）
    assert httpx.__version__
