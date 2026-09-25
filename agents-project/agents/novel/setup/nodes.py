"""开书 agent 的四个节点：collect 问、wait 停、confirm 过目、save 落库。

控制流全在图里（六项齐了没、去 confirm 还是去 wait、认可了没），模型只干一件事：
**把这一轮的话说出来**。所以 collect 里是直调流式模型，不走 create_agent —— 它没有工具，
输出的散文逐字流给用户，标记块由这里切开收进 settings。

"用户改口就得改口"这一条是结构性的：settings 是一份完整的六项，每轮整份并进新的标记块，
改一个已经定过的项照样覆盖（不再有"缺项变少才算进展"那种判据）。
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt

from ..utils.model import MainModel, intentModel
from ..utils.novel_information import save_novel_meta
from ..utils.verdict import verdict
from .prompt import CONFIRM_PROMPT
from .references import SETUP_SYSTEM
from .settings import (
    SETTING_FIELDS,
    SETTING_LABELS,
    merge_settings,
    missing_fields,
    parse_setting_blocks,
    render_item,
    render_settings,
    split_reply,
)
from .state import SetupState

# 问题要逐字流给用户，所以这里**不能** disable_streaming（主图那几个模型都关着）。
# 温度比判词高一些：它要说人话、要接住用户的话茬。
_setupModel = MainModel(temperature=0.6)


def _last_human_message(messages) -> str:
    """从对话历史里找最后一条用户消息（纯文本），用在 _brief 里补上用户反馈。"""
    for message in reversed(messages or []):
        if isinstance(message, HumanMessage):
            content = getattr(message, "content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


def _brief(state: SetupState, pending: str) -> str:
    """这一轮给模型的交代：六项定到哪儿了、用户刚说了什么、这一轮该干什么。

    **只喂给这一趟模型，不进 state**：每轮都往 history 里塞一份对账清单，几轮下来真正的
    对话会被它淹掉。用户的原话则要进 history（collect 那边单独追加一条干净的）。

    只报"已定 / 还差"，不指定先问哪一项 —— 顺序是模型自己定的事（见 prompt.py）。
    """
    settings = state.get("settings") or {}
    settled = [
        f"{SETTING_LABELS[field]}：\n{render_item(field, settings[field])}"
        for field in SETTING_FIELDS
        if settings.get(field)
    ]
    missing = [SETTING_LABELS[field] for field in missing_fields(settings)]

    lines = []
    lines.append("【已经定下的】\n" + ("\n".join(settled) if settled else "（一项都还没定）"))
    lines.append("【还差的】" + ("、".join(missing) if missing else "（没有了）"))

    # 用户这一轮的原话：pending 可能是空的（从 confirm 回炉），此时从对话历史里捞最后一句。
    said = pending
    if not said:
        said = _last_human_message(state.get("messages") or [])
    if said:
        lines.append(f"用户刚说的是：\n\n{said}")
    else:
        lines.append("等着用户开口。")

    if missing:
        lines.append(
            "【这一轮】接住用户刚说的那句，再往下问；他改口了就按他最新的说法重拟 —— "
            "改了已经定过的那一项，把那一项**整个**重新附一遍标记块"
            "（不止一条的那几项——主角、世界规则——每一条都要列出来，"
            "一条都不能少，否则没列出的那条会被丢掉）。"
            "这一轮定下哪几项就附哪几项，还没定的一项都不附。"
        )
    else:
        has_list = any(
            isinstance(settings.get(f), list) for f in ("novel_protagonists", "novel_world_rules")
        )
        if has_list:
            lines.append(
                "【这一轮】六项都定过了，用户是在对整份设定提意见：只改他点到的项，"
                "其余一项都不动，改完把动过的那几项重新附一遍标记块。\n\n"
                "【重要】**绝对不要问新的问题，绝对不要重复问已经定下的项** —— "
                "用户不是在回答新问题，而是在对已定好的内容提修改意见。\n\n"
                "【重要】**主角和世界规则若有点到，必须把该条目的全部内容重新输出一遍**"
                "—— 例如主角原来有两人（苏晚、李四），用户只说改苏晚的性格，你也必须"
                "把李四原样抄回去，一条都不能少。整项替换机制会丢掉你没列出的条目。\n\n"
                "你看他说的那句是什么、改到对应的项上就行，别的事一概不要管。"
                "只输出他提到的那一项的标记块（多条目那两项必须全列），没提到的项一句都不要提。"
            )
        else:
            lines.append(
                "【这一轮】六项都定过了，用户是在对整份设定提意见：只改他点到的项，"
                "其余一项都不动，改完把动过的那几项重新附一遍标记块。\n\n"
                "【重要】**绝对不要问新的问题，绝对不要重复问已经定下的项** —— "
                "用户不是在回答新问题，而是在对已定好的内容提修改意见。"
                "你看他说的那句是什么、改到对应的项上就行，别的事一概不要管。"
                "只输出他提到的那一项的标记块，没提到的项一句都不要提。"
            )

    return "\n\n".join(lines)


async def collect(state: SetupState, config: RunnableConfig) -> dict:
    """这一轮要说的话：散文流给用户，标记块（用户看不见）收进 settings。"""
    pending = (state.get("user_message") or "").strip()
    brief = _brief(state, pending)

    reply = await _setupModel.ainvoke(
        [
            SystemMessage(content=SETUP_SYSTEM),
            *(state.get("messages") or []),
            HumanMessage(content=brief),
        ]
    )
    text = reply.content if isinstance(reply.content, str) else ""
    prose, blocks_text = split_reply(text)

    updates = merge_settings(parse_setting_blocks(blocks_text))
    settings = {**(state.get("settings") or {}), **updates}

    # 用户的原话只在这里进 history，进了就把 state 里那份清掉 —— 重跑不会追加两遍。
    appends = [HumanMessage(content=pending)] if pending else []
    return {
        "messages": [*appends, AIMessage(content=text)],
        "settings": settings,
        "question": prose,
        "user_message": "",
    }


def route_after_collect(state: SetupState) -> str:
    """六项齐了去请用户过目；没齐就停下来等他答（问题在 state["question"] 里）。"""
    return "confirm" if not missing_fields(state.get("settings") or {}) else "wait"


def wait(state: SetupState) -> dict:
    """停下来把这一轮的话交给用户，答了再接着问。

    **interrupt 必须单起一个节点**：节点恢复时会从头重跑，把它写进 collect 里会让模型
    再被喊一遍、重新流一遍。这里之前只读 state，重跑是幂等的。
    """
    question = (state.get("question") or "").strip()
    if not question:
        # 模型这一轮一句话都没交出来（不该发生）：兜一句，绝不停在一个空问题上。
        labels = "、".join(SETTING_LABELS[field] for field in missing_fields(state.get("settings") or {}))
        question = f"还差这几项没定：{labels or '六项以外的细节'}。你说说怎么定，我记下来。"
    answer = interrupt(question)
    return {"user_message": str(answer)}


async def confirm(state: SetupState, config: RunnableConfig) -> Command:
    """把整份设定摆给用户过目，等他答复：认可了去落库，要改就带着他的意见回炉。

    清单接在 collect 那轮散文的后面（散文是它的前缀），前端"收到 question 就整段替换"时
    观感上就是接着往下打，不是换了一个气泡。interrupt 之前只读 state。
    """
    settings = state.get("settings") or {}
    text = "\n\n".join(
        part
        for part in (
            (state.get("question") or "").strip(),
            f"六项都定了，请你过目：\n\n{render_settings(settings)}",
            "没问题我就记下来，这本书就算建好了；要改哪一项，直接说改哪里。",
        )
        if part
    )
    answer = interrupt(text)

    reply = await intentModel.ainvoke(
        [SystemMessage(content=CONFIRM_PROMPT), HumanMessage(content=str(answer))]
    )
    reply_text = reply.content if isinstance(reply.content, str) else ""
    approved, _ = verdict(reply_text, "confirmed")

    if approved:
        return Command(goto="save", update={"approved": True})
    # 没认可：只把用户的意见留在 history 里，不把整份 confirm 清单（已经很长了）加进去挤占上下文。
    # _brief 会在下一轮 collect 中通过 _last_human_message 从历史里找到这句反馈。
    return Command(
        goto="collect",
        update={
            "approved": False,
            "question": "",
            "user_message": "",
            "messages": [HumanMessage(content=str(answer))],
        },
    )


async def save(state: SetupState, config: RunnableConfig) -> dict:
    """设定齐了、用户也认可了才落库。

    认 state["saved"] 这道闸：`novel` 行是 UPSERT，但大纲与世界规则表没有 ON CONFLICT，
    重复走一遍会插出重复行。
    """
    settings = state.get("settings") or {}
    cfg = config.get("configurable") or {}
    novel_id = str(cfg.get("novel_id") or "")
    if state.get("saved") or not state.get("approved") or missing_fields(settings) or not novel_id:
        return {}

    await save_novel_meta(novel_id, str(cfg.get("user_id") or "0"), settings)
    return {
        "saved": True,
        "edit_note": (
            f"《{settings.get('novel_title') or '未命名'}》建好了，设定都记下了。"
            "回书架点开这本书，说一声就能开写第一章。"
        ),
    }


def route_start(state: SetupState) -> str:
    """已经建好的这本书不再走一遍：重复 POST 同一个 id 时直接收工（前端按 saved 处理）。"""
    return "done" if state.get("saved") else "collect"
