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

    if missing:
        lines.append(
            "【这一轮】接住用户刚说的那句，再往下问；他改口了就按他最新的说法重拟 —— "
            "改了已经定过的那一项，把那一项**整个**重新附一遍标记块（不止一条的那几项，"
            "每一条都要列出来）。这一轮定下哪几项就附哪几项，还没定的一项都不附。"
        )
    else:
        lines.append(
            "【这一轮】六项都定过了，用户是在对整份设定提意见：只改他点到的项，"
            "其余一项都不动，改完把动过的那几项重新附一遍标记块。"
        )

    if pending:
        lines.append(f"用户刚说的是：\n\n{pending}")
    else:
        lines.append("用户刚说的是他在上面那条消息里提的意见。")
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
    # 没认可：把这份清单与用户的意见一并留在 history 里再回炉 —— 模型看得见用户是在对着
    # 什么提意见。用户的原话已经由这里追加过了，所以 user_message 留空，别在 collect 里再来一遍。
    return Command(
        goto="collect",
        update={
            "approved": False,
            "question": "",
            "user_message": "",
            "messages": [AIMessage(content=text), HumanMessage(content=str(answer))],
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
