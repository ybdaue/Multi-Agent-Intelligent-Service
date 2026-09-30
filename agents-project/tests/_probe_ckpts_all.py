"""探测：遍历所有 thread 的 checkpoint，输出每个 thread 的最新 state 摘要。"""
import asyncio
import base64
import sys

sys.path.insert(0, ".")
import ormsgpack


def dec(b64):
    return ormsgpack.unpackb(base64.b64decode(b64), ext_hook=lambda code, payload: f"<ext {code}>")


async def main():
    from api.utils.db import pg_pool

    await pg_pool.open()
    nid = "novel-mucksf9y-jbbyyxcb"
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            'SELECT "checkpointId", "checkpointNs", state, "updatedAt" FROM checkpoint '
            'WHERE "threadId"=%s ORDER BY "updatedAt"',
            (nid,),
        )
        rows = await cur.fetchall()
    await pg_pool.close()

    seen = set()
    for cid, ns, state, at in rows:
        if ns:
            continue
        key = (cid, at)
        if key in seen:
            continue
        seen.add(key)
        try:
            data = dec(state["payload"]) if isinstance(state, dict) and "payload" in state else state
        except Exception as exc:
            print("=====", at, cid[:8], "解不开", exc)
            continue
        cv = data.get("channel_values", data) if isinstance(data, dict) else {}
        if not isinstance(cv, dict):
            print("=====", at, cid[:8], "非 dict")
            continue
        msgs = cv.get("messages") or []
        tail = ""
        if msgs:
            last = msgs[-1]
            tail = str(getattr(last, "content", last))[:60].replace("\n", " ")
        print(
            f"===== {at} id={cid[:8]} intension={cv.get('intension')!r} target={cv.get('target')} "
            f"msgs={len(msgs)} last={tail!r}"
        )
        ac = cv.get("active_chapter") or {}
        if isinstance(ac, dict):
            print(f"      active_chapter: order={ac.get('chapter_order')} id={str(ac.get('chapter_id'))[:12]!r} wc={ac.get('chapter_word_count')}")


asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
