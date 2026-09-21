from ..state import State


def classify(state: State) -> str:
    """读 intension 节点写入的意图，作为路由依据。

    只有 write / edit / chat 会往下放（认不出来的在那边就收尾了），映射表一定查得到。
    """
    return state["intension"]


def route_after_load(state: State) -> str:
    """设定齐了照意图去写 / 去改；库里没有这本书就收尾回用户一句话。

    闸认 fromDB：为假说明这本书还没建成 —— 开书是「新建小说」弹窗里那个独立图的事，
    这里不许动笔（writer 会拿一份空设定去写第一章）。load 已经把引导的话写进 edit_note，
    update 会把它说成一句话。
    """
    if not (state.get("novel") or {}).get("fromDB"):
        return "update"
    return state["intension"]
