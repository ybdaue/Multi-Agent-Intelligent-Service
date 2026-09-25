import asyncio, sys
sys.path.insert(0, ".")
async def main():
    from api.utils.db import pg_pool
    await pg_pool.open()
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='checkpoint' ORDER BY ordinal_position")
        for r in await cur.fetchall():
            print(r)
    await pg_pool.close()
asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
