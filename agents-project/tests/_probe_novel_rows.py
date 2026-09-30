"""探测：列出所有小说及其它关键表的总行数。"""
import asyncio
import sys

sys.path.insert(0, ".")


async def main():
    from api.utils.db import pg_pool

    await pg_pool.open()
    nid = "novel-mucksf9y-jbbyyxcb"
    async with pg_pool.connection() as conn:
        for sql, label in [
            ('SELECT id, "order", title, status, "wordCount", "createdAt", "updatedAt" '
             'FROM novel_chapter WHERE "novelId"=%s ORDER BY "order"', "chapters"),
            ('SELECT * FROM novel_run WHERE "novelId"=%s', "run"),
        ]:
            try:
                cur = await conn.execute(sql, (nid,))
                rows = await cur.fetchall()
                cols = [d.name for d in cur.description]
                print(f"----- {label}")
                if not cols:
                    continue
                print("  cols:", cols)
                for r in rows:
                    print("  ", dict(zip(cols, [str(v)[:40] for v in r])))
            except Exception as exc:
                print(f"----- {label} 失败：{type(exc).__name__}: {exc}")
        cur = await conn.execute(
            'SELECT id, title, "createdAt" FROM novel WHERE id=%s', (nid,)
        )
        print("----- novel:", await cur.fetchall())
    await pg_pool.close()


asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
