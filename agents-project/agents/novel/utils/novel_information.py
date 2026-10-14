"""小说 agent 的信息读写：load 读（拉小说行与主角），开书图的 save 整本写。

大纲、世界规则这些量大又按章生效的不在这里拉，由 ChapterMeta 按章取。
一个 thread 就是一本小说，读按 (user id, novel id) 双 key 定位，与写入端一个口径。
"""

NOVEL_SQL = (
    'SELECT id, title, "wordCount", tropes, style, "reviewEnabled" FROM novel '
    'WHERE id = %s AND "userId" = %s'
)

PROTAGONIST_SQL = (
    'SELECT id, name, sex, age, "birthYear", "deathYear", identity, personality, '
    'ability, description, role FROM novel_character '
    'WHERE "novelId" = %s AND role = %s ORDER BY "createdAt"'
)

def empty_novel() -> dict:
    """还没有小说行时的空设定，字段与 NovelMeta 对齐。"""
    return {
        "novel_id": "",
        "novel_title": "",
        "novel_word_count": 0,
        "novel_tropes": "",
        "novel_style": "",
        "novel_review_enabled": True,
        "novel_outlines": [],
        "novel_world_rules": [],
        "novel_protagonists": [],
        "fromDB": False,
    }


def _character_payload(row: tuple) -> dict:
    id_, name, sex, age, birth_year, death_year, identity, personality, ability, description, role = row
    return {
        "id": id_,
        "name": name,
        "sex": sex,
        "age": age,
        "birthYear": birth_year,
        "deathYear": death_year,
        "identity": identity,
        "personality": personality,
        "ability": ability,
        "description": description,
        "role": role,
    }


def render_protagonists(novel: dict) -> str:
    """把 state 里已有的主角人设排成给人看的几行（writer 照着写、reader 核对 OOC），不再查库。"""
    lines = []
    for character in novel.get("novel_protagonists") or []:
        facts = [
            f"{label}{character.get(key)}"
            for key, label in (
                ("sex", "性别"),
                ("age", "年龄"),
                ("identity", "身份"),
                ("personality", "性格"),
                ("ability", "能力/金手指"),
                ("description", "其他"),
            )
            if character.get(key)
        ]
        lines.append(f"- {character.get('name') or '未命名'}" + ("：" + "；".join(facts) if facts else ""))
    return "\n".join(lines)


async def get_novel_meta(novel_id, user_id) -> dict:
    """取这本小说的小说级设定，字段与 NovelMeta 对齐。

    按 (novel id, user id) 双 key 取，撞线程 id 也读不到别人的小说；没有小说行就返回空设定。
    """
    from api.utils.db import pg_pool

    novel = empty_novel()
    novel["novel_id"] = novel_id

    async with pg_pool.connection() as conn:
        cur = await conn.execute(NOVEL_SQL, (novel_id, user_id))
        novel_row = await cur.fetchone()
        if novel_row is None:
            return novel

        novel_id, title, word_count, tropes, style, review_enabled = novel_row

        cur = await conn.execute(PROTAGONIST_SQL, (novel_id, "主角"))
        protagonists = [_character_payload(r) for r in await cur.fetchall()]

    novel.update(
        {
            "novel_id": novel_id,
            "novel_title": title,
            "novel_word_count": word_count,
            "novel_tropes": tropes or "",
            "novel_style": style or "",
            "novel_review_enabled": True if review_enabled is None else bool(review_enabled),
            "novel_protagonists": protagonists,
            "fromDB": True,
        }
    )
    return novel


NOVEL_INSERT = (
    'INSERT INTO novel (id, "userId", title, tropes, style, "createdAt", "updatedAt") '
    "VALUES (%s, %s, %s, %s, %s, now(), now()) "
    'ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, tropes = EXCLUDED.tropes, '
    'style = EXCLUDED.style, "updatedAt" = now()'
)

CHARACTER_INSERT = (
    'INSERT INTO novel_character (id, "novelId", name, sex, age, "birthYear", "deathYear", '
    'description, identity, personality, ability, role, "createdAt", "updatedAt") '
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now()) "
    'ON CONFLICT ("novelId", name) DO UPDATE SET sex = EXCLUDED.sex, age = EXCLUDED.age, '
    '"birthYear" = EXCLUDED."birthYear", "deathYear" = EXCLUDED."deathYear", '
    'description = EXCLUDED.description, identity = EXCLUDED.identity, '
    'personality = EXCLUDED.personality, ability = EXCLUDED.ability, role = EXCLUDED.role, '
    '"updatedAt" = now()'
)

# 大纲的生效章节收集阶段用不上，留空表示整本通用；order 先占 0，将来排多卷再改。
# level 写死 main：开书收的这条就是全书主线，阶段线/支线由 writer 写到那儿时才在台账里报。
OUTLINE_INSERT = (
    'INSERT INTO novel_outline (id, "novelId", level, status, "order", content, "createdAt", "updatedAt") '
    "VALUES (%s, %s, %s, %s, %s, %s, now(), now())"
)

WORLD_RULE_INSERT = (
    'INSERT INTO novel_world_rule (id, "novelId", name, rule, status, "createdAt", "updatedAt") '
    "VALUES (%s, %s, %s, %s, %s, now(), now())"
)

# status 用前端章节那套取值（draft / done），收集出来的设定还没人审，先记 draft。
SETTING_STATUS = "draft"


async def save_novel_meta(novel_id: str, user_id: str, novel: dict) -> None:
    """把开书收齐的设定整本落库（setup 图的 save 节点调）：novel 一行，加主角、大纲、世界规则各若干行。

    novel id 就用 config 里的 novel_id，带 user id 是为了不串数据；全在事务里写。
    """
    from api.utils.db import pg_pool
    import uuid

    async with pg_pool.connection() as conn:
        async with conn.transaction():
            await conn.execute(
                NOVEL_INSERT,
                (
                    novel_id,
                    user_id,
                    novel.get("novel_title") or "",
                    novel.get("novel_tropes") or "",
                    novel.get("novel_style") or "",
                ),
            )

            for protagonist in novel.get("novel_protagonists") or []:
                await conn.execute(
                    CHARACTER_INSERT,
                    (
                        uuid.uuid4().hex,
                        novel_id,
                        protagonist.get("name") or "",
                        protagonist.get("sex") or "",
                        protagonist.get("age") or "",
                        protagonist.get("birthYear") or "",
                        protagonist.get("deathYear") or "",
                        protagonist.get("description") or "",
                        protagonist.get("identity") or "",
                        protagonist.get("personality") or "",
                        protagonist.get("ability") or "",
                        protagonist.get("role") or "主角",
                    ),
                )

            # 事务内预检查：大纲和世界规则表没有 UNIQUE 约束，重跑会插出重复行。
            # 放在同一笔事务里，与后续 INSERT 读到的是一致的。
            cur = await conn.execute(
                'SELECT 1 FROM novel_outline WHERE "novelId" = %s LIMIT 1', (novel_id,)
            )
            has_outlines = await cur.fetchone() is not None
            cur = await conn.execute(
                'SELECT 1 FROM novel_world_rule WHERE "novelId" = %s LIMIT 1', (novel_id,)
            )
            has_rules = await cur.fetchone() is not None

            if not has_outlines:
                for order, outline in enumerate(novel.get("novel_outlines") or []):
                    await conn.execute(
                        OUTLINE_INSERT,
                        (
                            uuid.uuid4().hex,
                            novel_id,
                            "main",
                            SETTING_STATUS,
                            order,
                            outline.get("content") or "",
                        ),
                    )

            if not has_rules:
                for world_rule in novel.get("novel_world_rules") or []:
                    await conn.execute(
                        WORLD_RULE_INSERT,
                        (
                            uuid.uuid4().hex,
                            novel_id,
                            world_rule.get("name") or "",
                            world_rule.get("rule") or "",
                            SETTING_STATUS,
                        ),
                    )
