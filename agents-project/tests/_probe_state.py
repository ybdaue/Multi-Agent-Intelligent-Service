"""探测：列出指定 thread 的 task 及其中断点信息。"""
import asyncio
import json
import sys

sys.path.insert(0, ".")


async def main():
    from agents.novel import novel_agent
    from api.novel.agent import _config
    from api.utils.db import pg_pool

    await pg_pool.open()
    nid = "novel-mucksf9y-jbbyyxcb"
    uid = "De2gdvqty8mJBpX8SdYcQjTdGeacL2Ef"
    cfg = _config(uid, nid)
    snap = await novel_agent.aget_state(cfg)
    vals = snap.values or {}
    print("next:", snap.next)
    print("created_at:", snap.created_at)
    print("intension:", vals.get("intension"))
    print("target:", vals.get("target"))
    print("target_chapter:", vals.get("target_chapter"))
    print("named_chapter_order:", vals.get("named_chapter_order"))
    print("error:", vals.get("error"))
    ac = vals.get("active_chapter") or {}
    print("active_chapter:", json.dumps({k: (str(v)[:30] if "content" in k else v) for k, v in ac.items()}, ensure_ascii=False)[:400])
    msgs = vals.get("messages") or []
    print("messages:", len(msgs))
    for m in msgs[-4:]:
        print("   -", type(m).__name__, str(getattr(m, "content", ""))[:120].replace("\n", " "))
    for task in snap.tasks or ():
        print("task:", task.name, "interrupts:", [getattr(i, "value", None) for i in (task.interrupts or ())])
    await pg_pool.close()


asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
