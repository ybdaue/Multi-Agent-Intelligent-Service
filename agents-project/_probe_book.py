import asyncio, sys
sys.path.insert(0, ".")

async def main():
    from api.utils.db import pg_pool
    await pg_pool.open()
    nid = "novel-mucksf9y-jbbyyxcb"
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            'SELECT id,"order",title,status,"wordCount","createdAt","updatedAt",'
            'left(coalesce(content,\'\'),60) FROM novel_chapter WHERE "novelId"=%s ORDER BY "order"', (nid,))
        for r in await cur.fetchall():
            print(r)
        print("--- 书 ---")
        cur = await conn.execute('SELECT title,"wordCount","updatedAt" FROM novel WHERE id=%s', (nid,))
        print(await cur.fetchall())
    await pg_pool.close()

asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
