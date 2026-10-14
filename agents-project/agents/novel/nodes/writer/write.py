"""write 节点：写手 agent —— 照任务卡 + 上一章全文 + 设定档案把正文写出来。

不挂 fetchDB（查库已由 prepare 一次备齐，planner 也把要用的设定列进任务卡了）；只挂读技能文档
的工具（SKILL.md 已预读进系统提示，references 按需再读），也不挂"交稿"工具（正文与台账就是
模型的回复，切开与落库是 collect 的事）。开着流式：这一路的 token 要逐字发给前端当打字机。
ToolCallLimitMiddleware 兜底：写正文阶段本就该少调工具，限它一轮最多调 2 次，防 ReAct 反复
堆上下文、加延迟（超额的调用被挡回，模型拿已有信息收尾）。
"""
from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware

from ...tools import read_skill_file
from .helpers import _writer_main, _writer_system_prompt
from .state import WriterState

_writer_agent = create_agent(
    model=_writer_main,
    tools=[read_skill_file],
    middleware=[ToolCallLimitMiddleware(run_limit=2, exit_behavior="continue")],
    system_prompt=_writer_system_prompt(),
    state_schema=WriterState,
)