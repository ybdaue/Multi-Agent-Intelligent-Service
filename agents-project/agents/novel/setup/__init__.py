"""开书 agent：只在「新建小说」弹窗里用，主图不带它。

五节点架构：
  - greeting（暖场）：第一句友好的"想开一本什么样的书？"，interrupt 等用户答复
  - maintain（提取+路由）：调 LLM 读取最近 AIMessage + user_message，提取结构化设定，
    处理依赖，路由到 confirm 或 discuss
  - discuss（对话-生成）：调 LLM 生成问题，存到 state.question，路由到 ask_user
  - ask_user（对话-中断）：读 state.question 执行 interrupt，resume 后直接路由到 maintain
  - confirm（过目）：列出全部设定，调 intentModel 判认可，认可去 save，退回走 maintain

图结构：
    START ─▶ greeting ─▶ maintain ─▶ discuss ─▶ ask_user ─▶ maintain（循环）
                                │         │                  │
                                │         └── 自环 ──────────┘
                                └─▶ confirm ─▶ save ─▶ END
                                       │
                                       退回 ──▶ maintain

maintain 的 LLM 调用不存入 messages，是一次性分析。messages 只存 AIMessage（discuss 问的问题 /
greeting 的问候），用户的回答只存最新的在 user_message。ask_user 不调 LLM，只 interrupt。"""
from langgraph.graph import END, START, StateGraph

from ...utils.checkpoint import create_checkpoint
from ..utils.trace import traced
from .nodes import ask_user, confirm, discuss, greeting, maintain, route_start, save
from .state import SetupInput, SetupState

_setup_flow = StateGraph(SetupState, input_schema=SetupInput)
_setup_flow.add_node("greeting", traced("setup.greeting")(greeting))
_setup_flow.add_node("maintain", traced("setup.maintain")(maintain))
_setup_flow.add_node("discuss", traced("setup.discuss")(discuss))
_setup_flow.add_node("ask_user", traced("setup.ask_user")(ask_user))
_setup_flow.add_node("confirm", traced("setup.confirm")(confirm))
_setup_flow.add_node("save", traced("setup.save")(save))

# START → greeting（已落库的直接 END）
_setup_flow.add_conditional_edges(START, route_start, {"greeting": "greeting", "done": END})
# 各节点通过 Command(goto=...) 自行路由
_setup_flow.add_edge("save", END)

novel_setup_agent = _setup_flow.compile(
    name="novel_setup", checkpointer=create_checkpoint("novel_setup")
)