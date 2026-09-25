from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from ..state import State
from ..utils.novel_information import get_novel_meta


async def load(state: State, store: BaseStore, config: RunnableConfig) -> dict:
    """把这本书的小说级设定拉出来填进 NovelMeta。

    每轮都重读：书名、类型、文风、总字数用户在界面上改过之后，这一轮就得看见新值
    （早退过就再也不会变，改文风的入口会变成一句谎话）。代价是每轮多一条带索引的查询。
    库里没有就填一份空设定（fromDB 为假）：这本书还没建成，route_after_load 会把它转去
    update 回用户一句话。novel_id 就是小说 id（与 thread_id 相等），带 user_id 是为了
    id 撞车时不串数据。

    这一轮要动的是哪一章不在这儿定 —— 请求钉的那一章在 intension（见 nodes/intension.py），
    真正定下来在 resolve。
    """
    cfg = config["configurable"]
    novel = await get_novel_meta(cfg.get("novel_id"), str(cfg.get("user_id") or "0"))
    if not novel.get("fromDB"):
        # 开书只走弹窗里那个独立图（agents/novel/setup），这里没得问，直接给出去哪儿建。
        return {"novel": novel, "edit_note": "这本书还没有设定，先去左侧「新建小说」建一本，再回来写。"}
    return {"novel": novel}
