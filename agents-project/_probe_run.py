import asyncio, sys
sys.path.insert(0, ".")

async def main():
    from api.utils.db import pg_pool
    await pg_pool.open()
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            'SELECT "userId", key, value, "updatedAt" FROM agent_store '
            "WHERE \"agentName\"='novel_agent' AND key LIKE 'novel_run/%' ORDER BY \"updatedAt\" DESC LIMIT 8"
        )
        for uid, key, value, at in await cur.fetchall():
            print(at, key, value)
    await pg_pool.close()

asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
