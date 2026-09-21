"""端到端检测：让 novel_agent 照大纲写第一章，验流程与落库，跑完把这次写的数据删干净。

跑法（在 agents-project 下，-X utf8 不能省：依赖里有 emoji，撞 GBK 会报编码错）：

    .venv/Scripts/python -X utf8 agents/novel/test/test_write_chapter.py

先铺一份六项齐的合成设定让 load 拿到 fromDB，再走 api.novel.agent 的真实入口：
run_novel 跑到 writer → reader 后按新流程停在 confirm_chapter 上（不管审没审过都要问用户），
拿到问题后 resume_novel("收下") 接着跑完 update，最后查流程（意图 write、字段齐）与落库
（章节、总字数、checkpoint）。
只写删本次 novel id：novel 及其级联的 chapter / character / outline / world_rule，
外加本 thread 的 checkpoint；agent_store 不碰。要跑几分钟。
"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback
import uuid
from pathlib import Path

from dotenv import load_dotenv

# 独立脚本，不经 api.utils.config：自己把项目根塞进 sys.path、自己加载 env。
PROJECT_ROOT = Path(__file__).resolve().parents[3]  # agents/novel/test/x.py -> agents-project/
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 必须在 import agents 之前加载：模型实例是模块级构造的，import 时就要读到 key。
_env_names = [".env.development"]
if os.getenv("APP_ENV", "").strip().lower() in ("production", "prod"):
    _env_names.insert(0, ".env.production")
for _name in _env_names:
    if (PROJECT_ROOT / _name).exists():
        load_dotenv(PROJECT_ROOT / _name)
        break

from api.novel.agent import resume_novel, run_novel  # noqa: E402
from api.utils.db import pg_pool  # noqa: E402
from agents.novel.utils.chapter_information import (  # noqa: E402
    CHAPTER_MAX_WORDS,
    CHAPTER_MIN_WORDS,
)
from agents.novel.utils.novel_information import save_novel_meta  # noqa: E402

# 测试书 id 的固定前缀：清理只认这个前缀，防止误删真数据。
NOVEL_PREFIX = "test-novel-"
AGENT_NAME = "novel_agent"  # 与 agents/novel/__init__.py 里 create_checkpoint 的名字一致
MESSAGE = "照大纲把第一章写出来。"

# 六项齐的合成设定：值本身不重要，齐了 load 才拿得到 fromDB、route_after_load 才放行去写。
SEED_NOVEL = {
    "novel_title": "检测用短篇",
    "novel_tropes": "逆袭打脸 + 都市异能 + 扮猪吃虎",
    "novel_style": "快节奏、短句、对话多",
    "novel_protagonists": [
        {
            "name": "林默",
            "sex": "男",
            "age": "22",
            "birthYear": "",
            "deathYear": "",
            "identity": "外卖员",
            "personality": "嘴硬心软，认死理",
            "ability": "能听见三秒内别人即将出口的话",
            "description": "住城中村，穷但仗义",
            "role": "主角",
        }
    ],
    "novel_outlines": [
        {"content": "第 1 章：林默送外卖时撞见一场交易，觉醒听见心声的能力，被卷入其中。"}
    ],
    "novel_world_rules": [
        {"name": "心声", "rule": "只能听见三秒内即将出口的话，一天不超过五次，用多了耳鸣。"}
    ],
}


class Checks:
    """边查边记，最后一次性汇总；warn_only 只提示不算失败（字数、精简由模型产出决定）。"""

    def __init__(self) -> None:
        self.items: list[tuple[bool, str, str]] = []

    def check(
        self,
        ok: object,
        label: str,
        note: str = "",
        fail: str = "",
        warn_only: bool = False,
    ) -> bool:
        ok = bool(ok)
        tag = "[OK]  " if ok else ("[WARN]" if warn_only else "[FAIL]")
        line = f"  {tag} {label}"
        if note:
            line += f" —— {note}"
        if not ok and fail:
            line += f"（{fail}）"
        print(line)
        self.items.append((ok or warn_only, label, note))
        return ok

    @property
    def failed(self) -> list[tuple[bool, str, str]]:
        return [item for item in self.items if not item[0]]


async def _pick_user() -> str:
    """跑图的账号：优先 NOVEL_TEST_USER_ID，否则取库里第一个用户（novel.userId 有外键）。"""
    env_user = (os.getenv("NOVEL_TEST_USER_ID") or "").strip()
    if env_user:
        return env_user
    async with pg_pool.connection() as conn:
        cur = await conn.execute('SELECT id FROM "User" ORDER BY "createdAt" LIMIT 1')
        row = await cur.fetchone()
    return row[0] if row else ""


async def _seed_novel(novel_id: str, user_id: str) -> None:
    """铺一本六项齐的测试书，让 load 走 fromDB 那条路。"""
    await save_novel_meta(novel_id, user_id, SEED_NOVEL)


async def _chapters(novel_id: str) -> list[tuple]:
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            'SELECT id, title, "order", status, "wordCount", summary, "pastSummary", content '
            'FROM novel_chapter WHERE "novelId" = %s ORDER BY "order"',
            (novel_id,),
        )
        return list(await cur.fetchall())


async def _novel_word_count(novel_id: str) -> int | None:
    async with pg_pool.connection() as conn:
        cur = await conn.execute('SELECT "wordCount" FROM novel WHERE id = %s', (novel_id,))
        row = await cur.fetchone()
    return row[0] if row else None


async def _checkpoint_count(novel_id: str) -> int:
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            'SELECT COUNT(*) FROM checkpoint WHERE "agentName" = %s AND "threadId" = %s',
            (AGENT_NAME, novel_id),
        )
        row = await cur.fetchone()
    return row[0] if row else 0


async def _cleanup(novel_id: str) -> None:
    """删掉这次跑出来的所有行，再复查一遍确实没了。"""
    if not novel_id.startswith(NOVEL_PREFIX):
        raise RuntimeError(f"拒绝清理：{novel_id} 不带 {NOVEL_PREFIX} 前缀，怕删到真数据")

    async with pg_pool.connection() as conn:
        # novel 上挂了 chapter / character / outline / world_rule 的级联删除。
        await conn.execute("DELETE FROM novel WHERE id = %s", (novel_id,))
        await conn.execute(
            'DELETE FROM checkpoint WHERE "agentName" = %s AND "threadId" = %s',
            (AGENT_NAME, novel_id),
        )
        await conn.commit()

    left = await _chapters(novel_id)
    left_novel = await _novel_word_count(novel_id)
    left_cp = await _checkpoint_count(novel_id)
    print("\n[清理]")
    print(f"  novel_chapter 剩 {len(left)} 行；novel 行 {'还在' if left_novel is not None else '已删'}；"
          f"checkpoint 剩 {left_cp} 行")
    if left or left_novel is not None or left_cp:
        print("  [FAIL] 测试数据没删干净，请手动检查上面这个 novel id")
    else:
        print("  [OK]   测试数据已清空，库回到跑之前的样子")


async def main() -> int:
    await pg_pool.open()
    checks = Checks()
    novel_id = f"{NOVEL_PREFIX}{uuid.uuid4().hex[:12]}"

    try:
        user_id = await _pick_user()
        if not user_id:
            print('库里一个 User 都没有，没法建测试书。可用 NOVEL_TEST_USER_ID 指定账号。')
            return 2

        print(f"测试书 id：{novel_id}\n账号：{user_id}\n给它铺一份设定…")
        await _seed_novel(novel_id, user_id)

        print(f"\n[跑图] run_novel：{MESSAGE}")
        try:
            result = await run_novel(user_id=user_id, novel_id=novel_id, message=MESSAGE)
            crashed = None
        except Exception:
            result, crashed = {}, traceback.format_exc()

        print("\n[流程]")
        if crashed:
            checks.check(False, "图跑完没抛异常", crashed.strip().splitlines()[-1])
            print(crashed)
            return 1

        checks.check(
            bool(result.get("interrupted")),
            "writer → reader 之后停在 confirm_chapter 上等用户确认",
            f"图问的是：{result.get('question')}" if result.get("question") else "结果里没有 question",
        )
        if not result.get("interrupted"):
            return 1
        question = result.get("question") or ""
        checks.check(
            "第 1 章" in question and ("过了" in question or "没过" in question),
            "问的是第 1 章的审稿结论（过没过都要问）",
            question,
        )
        print(f"  图停下问：{question}")

        print(f"\n[收下] resume_novel：收下")
        try:
            result = await resume_novel(user_id=user_id, novel_id=novel_id, answer="收下")
            crashed = None
        except Exception:
            result, crashed = {}, traceback.format_exc()
        if crashed:
            checks.check(False, "resume 跑完没抛异常", crashed.strip().splitlines()[-1])
            print(crashed)
            return 1

        checks.check(
            not result.get("interrupted"),
            "收下之后没再停下（应该一路走到 update 落库）",
            f"又问了：{result.get('question')}" if result.get("interrupted") else "",
        )
        if result.get("interrupted"):
            return 1
        # intension 是 resume 之后才从最终 state 里读得到的（停顿时 _payload 只回问题）。
        checks.check(result.get("intension") == "write", "意图识别成 write", str(result.get("intension")))
        checks.check(
            bool(result.get("chapterId")),
            "state 里这一章回了 chapter_id（说明 update 落完库回填了）",
            str(result.get("chapterId")),
        )
        checks.check(result.get("chapterOrder") == 1, "新章序号是 1", str(result.get("chapterOrder")))

        words = result.get("chapterWordCount") or 0
        checks.check(words > 0, "state 里这一章有字数", f"{words} 字")
        checks.check(
            CHAPTER_MIN_WORDS <= words <= CHAPTER_MAX_WORDS,
            f"字数落在 {CHAPTER_MIN_WORDS}-{CHAPTER_MAX_WORDS}",
            f"{words} 字",
            warn_only=True,
        )

        print("\n[落库]")
        rows = await _chapters(novel_id)
        checks.check(len(rows) == 1, "novel_chapter 里正好一行", f"{len(rows)} 行")
        if not rows:
            return 1

        chapter_id, title, order, status, word_count, summary, past_summary, content = rows[0]
        checks.check(chapter_id == result.get("chapterId"), "库里的 id 与 state 回填的一致", chapter_id)
        checks.check(order == 1, "库里序号是 1", str(order))
        checks.check(bool((content or "").strip()), "正文落库了", f"{len(content or '')} 字符")
        checks.check("章" in (title or ""), "标题带「章」字（save 节点取的是 # 号行）", title or "（空）")
        checks.check(word_count == words, "库里的字数与 state 一致", f"{word_count} vs {words}")
        # summarize 节点产出的这两项，解析不出来会留空（下一章有「上一章全文」兜底），只提示。
        checks.check(
            bool(((past_summary or {}).get("text") or "").strip()),
            "前文总结落库了（summarize 节点产出）",
            note=f"{len((past_summary or {}).get('text') or '')} 字符",
            fail="空 —— summarize 那一次没解析出来，流程上允许，但值得看一眼",
            warn_only=True,
        )
        checks.check(
            bool((summary or "").strip()),
            "本章精简落库了",
            note=f"{len(summary or '')} 字符",
            fail="空 —— 同上",
            warn_only=True,
        )
        print(f"  章节状态：{status}")

        total = await _novel_word_count(novel_id)
        checks.check(
            total == word_count,
            'novel."wordCount" 与章节字数对得上（update 顺手刷的那一笔）',
            f"全书 {total} vs 本章 {word_count}",
        )
        checks.check(await _checkpoint_count(novel_id) > 0, "checkpoint 落了这一 thread 的快照")

        print("\n[正文开头 200 字]")
        print("  " + (content or "")[:200].replace("\n", "\n  "))

        print("\n[汇总]")
        if checks.failed:
            print(f"  {len(checks.failed)} 项没过：")
            for _, label, detail in checks.failed:
                print(f"   - {label}" + (f"（{detail}）" if detail else ""))
            return 1
        print("  全部通过。")
        return 0

    finally:
        await _cleanup(novel_id)
        await pg_pool.close()


if __name__ == "__main__":
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    sys.exit(asyncio.run(main(), loop_factory=loop_factory))
