from ..utils import intentModel
from ..state import State
from langgraph.types import Command
from langgraph.graph import END
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from ..utils import INTENT_PROMPT, _intentModel_backup, recent_history
from ..utils.chapter_information import get_chapter_order
from ..utils.retry import with_retry_and_fallback
from typing import Optional
import json


async def _pin(config: RunnableConfig) -> dict:
    """把请求里的 chapterId 解析成这一轮钉住的章节。

    用户开着哪一章只有请求知道 —— 模型看不见他的屏幕，手上只有一份章节清单和他说的话，
    所以"把这一章改一下"里的"这一章"只能从这儿来。只有"改"这一路才调它：写新章由 writer
    按库里的 max+1 定序号，改设定挂在书上，两条路都不认章号。解析不出来（本地新建还没落库
    的章、已经删了的章、压根没带）就交空。
    """
    cfg = (config or {}).get("configurable") or {}
    novel_id = cfg.get("novel_id")
    chapter_id = str(cfg.get("chapter_id") or "")
    if not novel_id or not chapter_id:
        return {}

    order = await get_chapter_order(novel_id, chapter_id)
    if order is None:
        return {}
    return {"chapter_id": chapter_id, "chapter_order": order}


def _named_order(said) -> Optional[int]:
    """模型报的章号转个整数；没点名（null）或压根不是数就交 None。"""
    try:
        return int(said)
    except (TypeError, ValueError):
        return None


async def _intent_node(state: State, config: RunnableConfig):
    user_message = state.get("user_message", "")
    history = recent_history(state.get("messages"), state.get("chat_summary") or "")

    system_content = f"""{INTENT_PROMPT}
            # 当前对话上下文（识别意图时必须结合）
            对话历史（最新在最后）：
            {history}"""

    try:
        response = await intentModel.ainvoke([SystemMessage(system_content), HumanMessage(user_message)])
    except Exception:
        try:
            response = await _intentModel_backup.ainvoke([SystemMessage(system_content), HumanMessage(user_message)])
        except Exception:
            raise

    try:
        parsed = json.loads(response.content)
        print("识别到用户意图", user_message, parsed)
    except json.JSONDecodeError:
        parsed = {}

    intension = parsed.get("intension")
    # 认不出来的（unknow / 没见过的词 / JSON 解不出）直接收尾告知用户，不做关键词猜测。
    # 认不出的值**不许**往下传：父图条件边拿它查映射表，查不到就是 KeyError 把整轮跑崩。
    if intension not in ("write", "edit", "chat"):
        return Command(
            update={
                "error": "无法识别意图",
                "messages": [
                    HumanMessage(content=user_message),
                    AIMessage(
                        content="抱歉，我没能理解您的需求。请把想做的事描述得具体一点，"
                        "例如让我修改小说章节或者续写新的小说章节。"
                    ),
                ],
            },
            goto=END,
        )

    # 只有"改"这一路才认章号：目标可能是章节正文，得先钉住他正开着的那一章。写新章由 writer
    # 按库里的 max+1 定序号，改设定挂在书上，两条路都不碰 chapterId，也就不必查这一趟库。
    target = await _pin(config) if intension == "edit" else {}

    # 用户这一句必须写回 messages：此前只有助手回复进 messages，模型看到的"历史"是一串
    # 没头没尾的自说自话，同一章里再问一遍就答不上来（user_message 每轮被覆盖，上一句早没了）。
    # 意图这一节点每轮都过，放这儿才能把闲聊、写作、修改三条路都记上。
    return {
        "intension": intension,
        "target_chapter": target,
        # 他话里点名的章号留给 editor：确认改的是章节正文之后，拿它跟钉住的那一章比一比。
        "named_chapter_order": _named_order(parsed.get("chapterOrder")),
        "messages": [HumanMessage(content=user_message)],
    }


def _intent_fallback(state, error=None):
    return Command(
        update={
            "error": f"意图识别服务不可用：{error}",
            "messages": [AIMessage(content="抱歉，意图识别服务暂时不可用，请稍后再试。")],
        },
        goto=END
    )


# 模型掉线、超时都从 _intent_node 里冒出来，没人接就是整轮 500。包一层：重试仍不行就由
# _intent_fallback 回一句话收尾（goto=END）。对外仍是 intension 这个名字。
intension = with_retry_and_fallback(_intent_node, _intent_fallback)
