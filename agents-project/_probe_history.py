import asyncio
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
    count = 0
    async for snap in novel_agent.aget_state_history(cfg):
        vals = snap.values or {}
        count += 1
        msgs = vals.get("messages") or []
        last = str(getattr(msgs[-1], "content", ""))[:70].replace("\n", " ") if msgs else ""
        print(
            f"{count:>2} next={snap.next} intension={vals.get('intension')!r} "
            f"target={vals.get('target')} user={str(vals.get('user_message'))[:40]!r} "
            f"msgs={len(msgs)} last={last!r}"
        )
        ac = vals.get("active_chapter") or {}
        print(f"      active_chapter: order={ac.get('chapter_order')} id={str(ac.get('chapter_id'))[:12]!r} wc={ac.get('chapter_word_count')}")
        if count > 40:
            break
    print("快照数：", count)
    await pg_pool.close()


asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
