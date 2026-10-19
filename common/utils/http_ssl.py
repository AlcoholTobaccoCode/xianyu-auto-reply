"""
HTTP SSL 信任配置

httpx 默认使用 certifi 证书包，无法识别 macOS 系统钥匙串或企业代理注入的
自签名 CA，本地开发时会报 CERTIFICATE_VERIFY_FAILED。

这里优先使用 truststore 读取操作系统信任库；不可用时回退 httpx 默认行为。
生产 Linux 容器使用系统 CA，效果一致。
"""
from __future__ import annotations

import ssl
from typing import Any


def build_httpx_verify() -> Any:
    """返回 httpx 可用的 verify 参数。

    - 有 truststore：使用系统信任库（macOS Keychain / Linux CA）
    - 没有 truststore：返回 True，保持 httpx 默认 certifi 行为
    """
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        return True
