"""运行期质量自检（进程内计数）。

教训（来自原项目）：辅助链路（纠错/记忆/摘要/重写）失败被 catch 吞掉时，界面完全正常，
用户只会以为"一切正常"。所以每条链路都记成功/失败，失败率超阈值就在 /health 里自报 degraded。
"""
from __future__ import annotations

from typing import Any

_counters: dict[str, int] = {}

# 辅助链路：ok 计数器 → fail 计数器
CHAINS: list[tuple[str, str, str]] = [
    ("analyst", "analyst_ok", "analyst_fail"),
    ("memory", "memory_ok", "memory_fail"),
    ("summary", "summary_ok", "summary_fail"),
    ("repair", "repair_ok", "repair_fail"),
]


def bump(name: str, amount: int = 1) -> None:
    _counters[name] = _counters.get(name, 0) + amount


def count_of(name: str) -> int:
    return _counters.get(name, 0)


def is_degraded(ok: int, fail: int, max_rate: float = 0.2, min_samples: int = 5) -> bool:
    """样本太少时失败率没有统计意义，先不判定。"""
    total = ok + fail
    if total < min_samples:
        return False
    return (fail / total) > max_rate


def snapshot() -> dict[str, Any]:
    chains = []
    for name, ok_key, fail_key in CHAINS:
        ok, fail = count_of(ok_key), count_of(fail_key)
        total = ok + fail
        chains.append(
            {
                "name": name,
                "ok": ok,
                "fail": fail,
                "rate": round(fail / total, 3) if total else 0.0,
                "degraded": is_degraded(ok, fail),
            }
        )
    return {
        "counters": dict(_counters),
        "chains": chains,
        "degraded": any(chain["degraded"] for chain in chains),
    }


def reset_for_test() -> None:
    _counters.clear()
