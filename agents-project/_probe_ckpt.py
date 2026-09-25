import asyncio, json, sys
sys.path.insert(0, ".")
async def main():
    from api.utils.db import pg_pool
    await pg_pool.open()
    nid = "novel-mucksf9y-jbbyyxcb"
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            'SELECT "checkpointNs", state, metadata, "updatedAt" FROM checkpoint '
            'WHERE "threadId"=%s ORDER BY "updatedAt" DESC LIMIT 4', (nid,))
        rows = await cur.fetchall()
    await pg_pool.close()
    for ns, state, meta, at in rows:
        print("=====", ns, at)
        print("  state keys:", list(state.keys()) if isinstance(state, dict) else type(state))
        if isinstance(state, dict):
            for k in ("intension", "target", "named_chapter_order", "error", "chat_summary"):
                if k in state:
                    print(f"    {k} =", json.dumps(state[k], ensure_ascii=False)[:200])
            ch = state.get("active_chapter")
            if isinstance(ch, dict):
                print("    active_chapter =", json.dumps({k: (str(v)[:30] if k == "chapter_content" else v) for k, v in ch.items()}, ensure_ascii=False)[:400])
            msgs = state.get("messages")
            if isinstance(msgs, list):
                print("    messages 条数:", len(msgs))
        print("  meta:", json.dumps(meta, ensure_ascii=False)[:200] if isinstance(meta, (dict, list)) else str(meta)[:200])
asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
