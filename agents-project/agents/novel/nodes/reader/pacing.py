"""pacing 节点：人物与设定审查（带 fetchDB，工具调用硬限 2 次）。"""
import time

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from ..utils.config import tool_config
from ..utils.reply import last_reply
from .helpers import _pacing_agent, _pacing_agent_backup
from .state import ReaderState


async def pacing(state: ReaderState, config: RunnableConfig) -> dict:
    """人物与设定审查：带 fetchDB，缺细节才点查（工具调用硬限 2 次）。"""
    content = state.get("pacing_input") or ""
    started = time.monotonic()
    tool_cfg = tool_config(config)
    report = ""
    for agent in (_pacing_agent, _pacing_agent_backup):
        if agent is None:
            continue
        try:
            result = await agent.ainvoke({"messages": [HumanMessage(content=content)]}, config=tool_cfg)
            report = last_reply(result.get("messages"))
            break
        except Exception:
            continue
    print(
        f"[reader] 人物设定审查完成，耗时 {time.monotonic() - started:.1f}s（输入 {len(content)} 字）"
    )
    return {"pacing_report": report}