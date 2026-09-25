"""开书 agent：只在「新建小说」弹窗里用，主图不带它。

把用户一句话方向问成六项设定、请他过目、落库，这条流程自己成一个图，自己一个 checkpoint 名
（`novel_setup`）—— 跟主图 `novel_agent` 各跑各的，同一个书 id 也不会互相踩快照。

一轮就是一次请求：模型把话说完（散文逐字流给用户，标记块收进 settings），图停在 wait 上等答复
（或六项齐了停在 confirm 上等过目）。下一句答复带着同一个 thread_id 回来，从停下的地方接着跑。

    START ─▶ collect ─▶ confirm ─▶ save ─▶ END
                │         │
                └▶ wait ──┘（不认可）─▶ collect
             wait 的 interrupt 把问题交给用户；已落过库就直接 END
"""
from langgraph.graph import END, START, StateGraph

from ...utils.checkpoint import create_checkpoint
from ..utils.trace import traced
from .nodes import collect, confirm, route_after_collect, route_start, save, wait
from .state import SetupInput, SetupState

# 进出一行人话打印（agents/novel/utils/trace.py），只管调式，不动流程。
_setup_flow = StateGraph(SetupState, input_schema=SetupInput)
_setup_flow.add_node("collect", traced("setup.collect")(collect))
_setup_flow.add_node("wait", traced("setup.wait")(wait))
_setup_flow.add_node("confirm", traced("setup.confirm")(confirm))
_setup_flow.add_node("save", traced("setup.save")(save))

_setup_flow.add_conditional_edges(START, route_start, {"collect": "collect", "done": END})
_setup_flow.add_conditional_edges(
    "collect", route_after_collect, {"confirm": "confirm", "wait": "wait"}
)
# 用户答了接着问（答复由 wait 写回 state）。
_setup_flow.add_edge("wait", "collect")
# confirm 与 collect 自己决定回炉还是往下走（Command 的 goto），两条路都在图里，不由模型挑。
_setup_flow.add_edge("save", END)

# 顶层图自己编译，所以得自己挂 checkpointer：wait / confirm 的 interrupt 要靠它存下来，
# 用户下一句答复带着同一个 thread_id 回来才接得上。名字与主图不同，两边快照各写各的。
novel_setup_agent = _setup_flow.compile(
    name="novel_setup", checkpointer=create_checkpoint("novel_setup")
)
