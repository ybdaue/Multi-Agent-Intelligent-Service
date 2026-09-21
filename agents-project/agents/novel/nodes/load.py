from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from ..state import State
from ..utils.novel_information import get_novel_meta


async def load(state: State, store: BaseStore, config: RunnableConfig) -> dict:
    """把这本书的小说级设定拉出来填进 NovelMeta。

    库里没有就填一份空设定（fromDB 为假）：这本书还没建成，route_after_load 会把它转去
    update 回用户一句话。state 里已有就不再查库。novel_id 就是小说 id（与 thread_id 相等），
    带 user_id 是为了 id 撞车时不串数据。

    这一轮要动的是哪一章不在这儿定 —— 那个在 intension 就钉好了（见 nodes/intension.py）。
    """
    if (state.get("novel") or {}).get("novel_id"):
        return {}

    cfg = config["configurable"]
    novel = await get_novel_meta(cfg.get("novel_id"), str(cfg.get("user_id") or "0"))
    if not novel.get("fromDB"):
        # 开书只走弹窗里那个独立图（agents/novel/setup），这里没得问，直接给出去哪儿建。
        return {"novel": novel, "edit_note": "这本书还没有设定，先去左侧「新建小说」建一本，再回来写。"}
    return {"novel": novel}
