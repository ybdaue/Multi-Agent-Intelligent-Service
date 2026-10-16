"""planner 节点：模型看材料（不看上一章全文）出一张任务卡，拼进写手的开场白。"""
from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from ...tools import fetchDB
from ...utils.ledger import fetch_names, fetch_relations
from ...utils.prompt import PLANNER_PROMPT
from ..utils.config import tool_config
from ..utils.reply import last_reply
from .helpers import (
    _briefing,
    _chosen_inspirations,
    _parse_card,
    _planner_input,
    _planner_main,
)
from .state import WriterState

# planner 会按需查库（本章突然要用很久以前出现的角色/势力等，材料里没给到细节时点查一条）。
# 工具调用硬限 2 次：提示词写明"最多查一次"，这里再用中间件挡住反复 ReAct（超额的调用被挡回，
# 模型照已有信息把卡出完，不会整个中断）。
_planner_agent = create_agent(
    model=_planner_main,
    tools=[fetchDB],
    middleware=[ToolCallLimitMiddleware(run_limit=2, exit_behavior="continue")],
    system_prompt=PLANNER_PROMPT,
    state_schema=WriterState,
)


def _card_character_names(card: dict) -> list[str]:
    """任务卡里报的本章要用的人物名：settings（库里已有）与 new（本章新造）里 refType==character 的。

    名字在这儿解析成 id，关系才由代码一并查出 —— planner 用 fetchDB 补查的人物也会写进 settings，
    不落到这里就会漏掉它身上的关系。
    """
    if not isinstance(card, dict):
        return []
    names = []
    for key in ("settings", "new"):
        rows = card.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or row.get("refType") != "character":
                continue
            if key == "settings":
                name = str(row.get("name") or "").strip()
            else:
                fields = row.get("fields")
                name = str(fields.get("name") or "").strip() if isinstance(fields, dict) else ""
            if name:
                names.append(name)
    return names


async def _chapter_relations(novel_id: str, bundle: dict, card: dict) -> list[dict]:
    """本章相关人物的关系：上一章台账里的人物（prepare 已备好 id）∪ 任务卡里报的人物（名字解析 id）。

    关系内容由**代码**查出带给写手，不靠 planner 转述。
    """
    ids = list(bundle.get("relation_char_ids") or [])
    names = _card_character_names(card)
    if names:
        known = {
            name: ref_id
            for ref_type, ref_id, name in await fetch_names(novel_id)
            if ref_type == "character"
        }
        for name in names:
            ref_id = known.get(name)
            if ref_id:
                ids.append(ref_id)
    return await fetch_relations(novel_id, ids)


async def planner(state: WriterState, config: RunnableConfig) -> dict:
    """出任务卡：模型看材料（不看上一章全文）出一张卡，把卡拼进写手的开场白。"""
    handed = {
        "chapter_attempt": state.get("chapter_attempt", 0) + 1,
        "chapter_review": {"passed": True, "problems": ""},
    }
    bundle = state.get("bundle") or {}
    if not bundle:
        return {
            **handed,
            "task_card": {},
            "chapter_inspirations": [],
            "messages": [HumanMessage(content="拿不到当前这本书的编号，写不了。")],
        }

    card = {}
    if _planner_agent is not None:
        try:
            result = await _planner_agent.ainvoke(
                {"messages": [HumanMessage(content=_planner_input(state))]},
                config=tool_config(config),
            )
            card = _parse_card(last_reply(result.get("messages")))
        except Exception:
            card = {}
    # 本章最终要用的灵感：代码从「必用 ∪ 用户点名 ∪ planner 从可选里挑的」合并定，不由模型拍板。
    chosen = _chosen_inspirations(state, card, bundle.get("inspirations") or {})
    # 本章相关人物的关系由代码补查：卡里报的人物（含 planner 用 fetchDB 补查的）与上一章台账里的
    # 人物取 id 并集，关系一并带给写手 —— 写手开场照这份，不靠模型转述关系内容。
    novel_id = (config.get("configurable") or {}).get("novel_id")
    if novel_id:
        bundle = {**bundle, "relations": await _chapter_relations(novel_id, bundle, card)}
    return {
        **handed,
        "task_card": card,
        "chapter_inspirations": chosen,
        "bundle": bundle,
        "messages": [HumanMessage(content=_briefing({**state, "bundle": bundle}, card, chosen))],
    }