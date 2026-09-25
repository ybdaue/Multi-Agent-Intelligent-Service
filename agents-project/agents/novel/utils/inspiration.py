"""灵感素材：用户在对话框里挂的图片 / 文件 / 链接，落 novel_inspiration 并渲染进提示词。

两种命运一分为二：**全部**落库（`add_inspirations`，附件是用户给的素材，哪怕这一轮没写成章
也该留着）；**能读成文字的**才进 prompt（`render_inspirations`）。图片与二进制读不了内容 ——
模型是纯文本的，所以只告诉它"有这么个东西、叫什么名字"，明说看不了，免得它以为读过。

`usedChapterIds` 由 update 落章后补（`mark_used`）：这一章用了哪几条素材，将来翻素材库看得到。
"""
import uuid

# 一条素材进 prompt 的字符上限：附件正文可能很长，别一条把上下文吃光。
MAX_INSPIRATION_CHARS = 4_000

# 给用户看的类型名，与前端 InspirationItem.kind 一一对应。
_KIND_LABEL = {"image": "图片", "file": "文件", "url": "链接"}

_INSERT_SQL = (
    'INSERT INTO novel_inspiration (id, "novelId", type, content, "usedChapterIds", '
    '"createdAt", "updatedAt") VALUES (%s, %s, %s, %s, %s, now(), now())'
)

# 追加而不是覆盖：同一条素材可能被好几章用到。
_USED_SQL = (
    'UPDATE novel_inspiration SET "usedChapterIds" = array_append("usedChapterIds", %s), '
    '"updatedAt" = now() WHERE id = ANY(%s) AND NOT ("usedChapterIds" @> ARRAY[%s]::text[])'
)


async def add_inspirations(novel_id: str, items: list[dict]) -> list[dict]:
    """这一轮带的素材落库，回填每条的 id（空列表不碰库）。"""
    if not items:
        return []

    from api.utils.db import pg_pool

    written = []
    async with pg_pool.connection() as conn:
        async with conn.transaction():
            for item in items:
                item_id = uuid.uuid4().hex
                await conn.execute(
                    _INSERT_SQL,
                    (
                        item_id,
                        novel_id,
                        item.get("type") or "file",
                        item.get("content") or "",
                        [],
                    ),
                )
                written.append({**item, "id": item_id})
    return written


async def mark_used(inspiration_ids: list[str], chapter_id: str) -> None:
    """把这一章记进那几条素材的 usedChapterIds（这一轮没带素材就什么都不做）。

    不再按 novelId 收窄：id 是本轮 add_inspirations 现发的，本来就属于这本书。
    """
    if not inspiration_ids or not chapter_id:
        return

    from api.utils.db import pg_pool

    async with pg_pool.connection() as conn:
        await conn.execute(_USED_SQL, (chapter_id, list(inspiration_ids), chapter_id))


def render_inspirations(items: list[dict]) -> str:
    """这一轮用户给的素材渲染成给模型看的一段；没有就返回空串（调用方据此决定插不插）。"""
    lines = []
    for item in items or ():
        name = (item.get("name") or "未命名").strip()
        label = _KIND_LABEL.get(item.get("type") or "", "素材")
        content = (item.get("content") or "").strip()
        if len(content) > MAX_INSPIRATION_CHARS:
            content = f"{content[:MAX_INSPIRATION_CHARS]}…（原 {len(content)} 字符，已截断）"
        lines.append(f"- 《{name}》（{label}）：{content or '（没读到内容）'}")
    return "\n".join(lines)
