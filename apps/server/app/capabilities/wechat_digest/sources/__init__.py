"""数据源注册与再导出。

新增数据源 = 新增一个模块 + 在这里注册一行，具体步骤见 ``base.py`` 顶部注释。
"""
from __future__ import annotations

from .base import (
    Message,
    MessageSource,
    SourceDescriptor,
    get_source,
    list_source_objects,
    list_sources,
    register_source,
)
from .paste import PasteSource, parse_transcript

# —— 内置数据源 ——
# 目前只有「粘贴文本」。以后接 OneBot / wechat-cli：
#   from .onebot import OneBotSource
#   register_source(OneBotSource())
register_source(PasteSource())

__all__ = [
    "Message",
    "MessageSource",
    "SourceDescriptor",
    "PasteSource",
    "get_source",
    "list_source_objects",
    "list_sources",
    "parse_transcript",
    "register_source",
]
