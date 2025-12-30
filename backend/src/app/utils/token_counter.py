"""Token 近似计数工具。"""

from __future__ import annotations


def count_tokens_approximately(text: str) -> int:
    """用稳定口径估算 token 数。

    说明：采用字符数除以 4 的粗略估算，保持历史一致性。
    """
    if not text:
        return 0
    return max(len(text) // 4, 1)
