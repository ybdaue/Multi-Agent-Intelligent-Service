"""探测：用 base64 解码 checkpoint payload，查看 thread 的完整 state 内容。"""
import asyncio
import base64
import json
import sys

sys.path.insert(0, ".")
import ormsgpack


def dec(b64):
    return ormsgpack.unpackb(base64.b64decode(b64))


async def main():
    from api.utils.db import pg_pool

    await pg_pool.open()
    nid = "novel-mucksf9y-jbbyyxcb"
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            'SELECT "checkpointId", "checkpointNs", state FROM checkpoint '
            'WHERE "threadId"=%s ORDER BY "updatedAt" DESC LIMIT 6',
            (nid,),
        )
        rows = await cur.fetchall()
    await pg_pool.close()
    print("rows:", len(rows))
    for cid, ns, state in rows:
        try:
            data = dec(state["payload"])
        except Exception as exc:
            print("=====", cid, "解不开", exc)
            continue
        print("=====", cid, "ns=", repr(ns), "top:", list(data.keys()))
        cv = data.get("channel_values", data)
        if isinstance(cv, dict):
            print("   cv keys:", list(cv.keys())[:40])
            for k in ("intension", "target", "named_chapter_order", "error"):
                if k in cv:
                    print(f"   {k} =", json.dumps(cv[k], ensure_ascii=False)[:200])
            ac = cv.get("active_chapter")
            if ac:
                print(
                    "   active_chapter:",
                    json.dumps(
                        {k: (str(v)[:25] if "content" in k else v) for k, v in ac.items()},
                        ensure_ascii=False,
                    )[:300],
                )


asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
