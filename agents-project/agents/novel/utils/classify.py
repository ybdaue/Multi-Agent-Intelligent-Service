from ..state import State


def classify(state: State) -> str:
    """读 intension 节点写入的意图，作为路由依据。

    只有 write / edit / chat 会往下放（认不出来的在那边就收尾了），映射表一定查得到。
    """
    return state["intension"]


def route_after_chat(state: State) -> str:
    """闲聊之后：手上还压着一份没确认的稿，就转回确认那一问；否则照旧收尾。

    从 confirm_chapter 转过来的闲聊是"用户没点按钮、而是问了一句"：他要的答复由 chat 给
    （问答在 messages 末尾），这一稿仍在 active_chapter 里等着 —— 不能让 chat 顺手走到
    update，那是把他没确认的稿落库了。判据跟 reader.gather / confirm_chapter / update
    同一个口径：正文非空、chapter_id 为空 = 这一稿还没落库。
    """
    chapter = state.get("active_chapter") or {}
    if chapter.get("chapter_content") and not chapter.get("chapter_id"):
        return "confirm_chapter"
    return "update"


def route_after_load(state: State) -> str:
    """设定齐了先去定目标（resolve）；库里没有这本书就收尾回用户一句话。

    闸认 fromDB：为假说明这本书还没建成 —— 开书是「新建小说」弹窗里那个独立图的事，
    这里不许动笔（writer 会拿一份空设定去写第一章）。load 已经把引导的话写进 edit_note，
    update 会把它说成一句话。
    """
    if not (state.get("novel") or {}).get("fromDB"):
        return "update"
    return state["intension"]


def route_after_resolve(state: State) -> str:
    """目标定了就分头去：续写走 writer，改稿走 editor。

    只读意图、不做判断 —— 拿不准的一律当续写（resolve 那条路的两个意图之外进不来）。
    """
    return "edit" if state.get("intension") == "edit" else "write"


def route_after_draft(state: State) -> str:
    """一稿写完 / 改完：审稿开着就去 reader 查一遍，关着就直接停下来问用户。

    开关由 load 按 novel.reviewEnabled 读进 state.review_enabled。关掉的书走 confirm_chapter
    —— 用户确认后落库，中间不插 reader 那一关（少了「正在审稿…」那道状态行）。
    """
    return "reader" if state.get("review_enabled", True) else "confirm_chapter"

