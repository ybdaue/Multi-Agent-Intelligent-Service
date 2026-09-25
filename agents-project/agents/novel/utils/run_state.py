"""这一轮跑到哪儿的标记：running / awaiting / done / cancelled。

落在 agent_store（这张表本来就在用），不新建表 —— 中断的那一轮没有章节行，novel 也没有状态列，
checkpoint 元数据又分不出「跑完」与「取消」，只有这里放得下。
namespace 用 novel_run / novelId / userId，末位是 userId 是 agent_store 的定位约定。
"""
from __future__ import annotations

from datetime import datetime, timezone

from agents.utils.agent_store import create_agent_store

RUNNING = "running"
AWAITING = "awaiting"
DONE = "done"
CANCELLED = "cancelled"

_KEY = "state"

_store = create_agent_store("novel_agent")


def _namespace(user_id: str, novel_id: str) -> tuple[str, str, str]:
    """这本书这个用户的标记放哪儿：末位必须是 userId（见 agent_store 的约定）。"""
    return ("novel_run", novel_id, str(user_id))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def read_run(user_id: str, novel_id: str) -> dict | None:
    """这一轮的最新状态；从没跑过就是 None。"""
    item = await _store.aget(_namespace(user_id, novel_id), _KEY)
    return dict(item.value) if item else None


async def mark_running(user_id: str, novel_id: str, chapter_id: str, intension: str | None = None) -> None:
    """开跑前盖一个 running：手改撞车时判 409 靠它，中断提示也靠它。"""
    await _store.aput(
        _namespace(user_id, novel_id),
        _KEY,
        {"status": RUNNING, "chapterId": chapter_id or "", "intension": intension, "at": _now()},
    )


async def mark_settled(user_id: str, novel_id: str, status: str) -> None:
    """收尾：把 running 换成 done / awaiting / cancelled，其余字段原样留着。"""
    run = await read_run(user_id, novel_id) or {}
    run.update({"status": status, "at": _now()})
    await _store.aput(_namespace(user_id, novel_id), _KEY, run)
