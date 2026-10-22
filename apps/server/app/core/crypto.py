"""API Key 加密：本机密钥文件（0600）+ Fernet，库里只存密文。"""
from __future__ import annotations

import logging
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    path = settings.data_dir / "secret.key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Fernet.generate_key())
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover - Windows
            pass
        log.info("已生成本机密钥文件 %s", path)
    return Fernet(path.read_bytes().strip())


def encrypt(plain: str | None) -> str | None:
    if not plain:
        return None
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        log.warning("API Key 解密失败（密钥文件可能已更换）")
        return None


def hint(plain: str | None) -> str | None:
    if not plain:
        return None
    if len(plain) <= 8:
        return "••••"
    return f"{plain[:3]}••••{plain[-4:]}"
