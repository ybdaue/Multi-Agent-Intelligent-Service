import json
import os
import uuid
from langchain_core.tools import tool
from typing import Annotated, Literal, Dict, Any, Optional, Union
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.graph import MessagesState
from langgraph.prebuilt import ToolNode, InjectedState
from agents.utils.models import MainModel
from .legal import legal_agent
from .utils.boundMemory import BoundedMemorySaver
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage, SystemMessage, HumanMessage


class FileSource(TypedDict):
    type: Literal["bytes","path","db"]
    suffix: str
    content: Union[str, bytes]
    file_id: str


class GlobalState(MessagesState):
    #输入内容
    userId: int
    user_message: str
    file_source: Optional[FileSource] = None
    #输出结果
    usedToken: int = 0
    output_file: Optional[FileSource] = None


# ===== 法律子 Agent 核心逻辑（无 @tool 装饰，避免 bytes 内容序列化问题） =====

async def _execute_legal_agent(msg: str, file_source=None, config=None):
    """执行法律子 Agent 的核心逻辑，file_source 来自 InjectedState，config 由工具参数注入。"""
    configurable = (config or {}).get("configurable", {})
    parent_thread_id = configurable.get("thread_id") or "unknown"
    user_id = configurable.get("userId")
    sub_thread_id = f"{parent_thread_id}_legal"

    result = await legal_agent.ainvoke(
        {
            "messages": [HumanMessage(msg)],
            "user_message": msg,
            "file_source": file_source,
            "userId": user_id,
        },
        {"configurable": {"thread_id": sub_thread_id, "userId": user_id}},
    )

    # 只返回相关字段，避免全量 state 污染主智能体上下文
    return json.dumps({
        "analysis_result": result.get("analysis_result"),
        "answer_result": result.get("answer_result"),
        "output_file": result.get("output_file"),
    }, ensure_ascii=False, default=str)



@tool
async def use_legal_agent(
    msg: str,
    config: RunnableConfig,
    fs: Annotated[Optional[FileSource], InjectedState("file_source")],
):
    """
    处理所有法律相关问题及文档审查。

    Args:
        msg: 用户当前的法律问题（只需传当前这一句话即可，专家有记忆）。
        fs: 用户上传的文件（由系统从 graph state 自动注入，模型不可见）。
    """
    return await _execute_legal_agent(msg=msg, file_source=fs, config=config)


@tool
async def use_finance_agent(msg: str):
    """
    处理所有股票/大盘/个股/基金/财报等金融证券相关问题。

    Args:
        msg: 用户的股票问题（需包含股票名称/代码和具体问题）
    """
    # TODO: 接入股票子 Agent
    return f"[股票分析暂未开通] 你的问题是：{msg}"


def _clean_legal_tool_result(content):
    """把 use_legal_agent 返回的原始 JSON 整理为可读文本。

    路由模型拿到原始 JSON 时可能原样回显，导致最终回答出现
    {"analysis_result":..., "answer_result":...} 之类的泄漏。
    这里在发送给模型前将其转成自然语言块，从源头避免 JSON 回显。
    """
    try:
        result = json.loads(content) if isinstance(content, str) else content
    except (json.JSONDecodeError, TypeError):
        return content
    if not isinstance(result, dict):
        return content

    parts = []
    analysis = result.get("analysis_result")
    if isinstance(analysis, dict):
        risks = analysis.get("risks") or []
        if risks:
            lines = ["文件分析结论："]
            for r in risks:
                lines.append(
                    f"- [{r.get('risk_level', '')}] {r.get('issue', '')}"
                    + (
                        f"（建议：{r.get('suggestion', '')}）"
                        if r.get("suggestion")
                        else ""
                    )
                )
            parts.append("\n".join(lines))
        elif analysis.get("summary"):
            parts.append(f"文件分析结论：{analysis['summary']}")
    elif analysis:
        parts.append(f"文件分析结论：{analysis}")

    answer = result.get("answer_result")
    if answer:
        parts.append(f"法律咨询答复：{answer}")

    of = result.get("output_file")
    fname = ""
    if isinstance(of, dict):
        path = of.get("content", "")
        if isinstance(path, str):
            fname = os.path.basename(path)
    elif isinstance(of, str):
        fname = os.path.basename(of)
    if fname:
        parts.append(f"已生成文书文件：{fname}")

    return "\n".join(parts) if parts else str(content)


llm_prompt="""
# Role
你是一个任务路由器。你的唯一职责是根据用户对话判断意图，并决定调用哪个专业工具来处理。
你**不是**法律或金融专家，**绝不**允许自行回答任何专业问题。

# 核心原则（最高优先级，必须遵守）

1. **除了日常对话（问候、感谢、闲聊、确认等），禁止直接回答任何其他问题。**
2. 只要是法律、金融、文件分析等专业需求，**必须**调用对应工具，严禁用自己的知识直接作答。
3. 调用工具时，**禁止输出任何自然语言文字**。不要写"好的""我来帮您""根据您上传的文件，我已经为您调用了专业XX工具进行分析"等寒暄或说明，直接发起工具调用，`msg` 参数填用户当前原话。
4. 工具返回结果后，直接呈现结果内容本身，**不要**加"根据您上传的文件，我已调用XX工具"之类的开场白或过程说明。

# 工作流程

## 第一阶段：意图路由
用户提问后，判断意图并调用对应的专业工具。
不做具体分析、不补全上下文、不替子 Agent 干活，把用户的话原样传给对应工具。

## 第二阶段：结果处理
工具返回结果后，基于结果中的字段生成语义化回答：

1. `analysis_result`（文件分析结果）：用自然语言向用户解释分析结论，包括风险点、风险等级和修改建议。
2. `answer_result`（法律咨询结果）：向用户呈现法律咨询的专业解答内容。
3. `output_file`（产出文件）：告知用户文件已生成及用途。

注意：直接给出结论本身，不要复述"我调用了哪个工具"这一过程。

# 可用工具

## use_legal_agent
- 功能：处理所有法律相关问题及文档审查。
- 参数：
  - `msg`（string，**必填**）：用户当前的问题原文，直接传，不需要你改写或补全。
  - `fs`（object，**自动注入，无需填写**）：用户上传的文件，由系统自动传入，你不要传。

## use_finance_agent
- 功能：处理所有股票/金融证券相关问题。
- 参数：
  - `msg`（string，**必填**）：用户当前的问题原文，直接传，不需要你改写或补全。
- 注意：**不支持文件**。如果用户上传了文件却在问股票，不要调工具，直接回复："股票分析暂不支持上传文件，请直接输入您想了解的股票相关问题。"

# 路由规则（按优先级从上到下判断）

0. **用户已上传了文件（见上方"文件状态"）** → 无论用户说什么（包括"看看""这个""分析一下"等），直接调 `use_legal_agent`。
1. **日常问候 / 闲聊 / 与金融法律无关的提问** → 不调工具，直接回答。
2. **明确是股票/金融问题** → 调 `use_finance_agent`。
3. **明确是法律问题** → 调 `use_legal_agent`。
4. **模糊不清（且无文件）** → 不调工具，直接回复："请问您是想咨询股票相关的问题，还是需要法律方面的帮助？"

# 历史对话处理

你收到的消息列表中包含完整对话历史。判断意图时需要参考历史，但：

- **`msg` 始终只传用户当前这一轮的原话**，不要拼接历史。
- **领域切换**：历史在法律领域，当前突然问股票 → 直接调 `use_finance_agent`，不要被历史带偏。反之亦然。
- **历史文件指代**：如果历史中用户已上传并分析过文件，当前消息用"继续""刚才那份""这个文件""再看看""分析一下"等指代该文件时，即使本轮没有新上传文件，也应调 `use_legal_agent`（`msg` 仍只传当前原话）。
- **结果轮不重复调用**：当本轮输入的最后一条已是"工具调用 + 工具返回结果"、且没有新的用户提问时，不要再调用任何工具，直接基于结果生成最终回答。

# 输出要求

- 始终使用中文回答用户，不要输出英文。
- 仅日常对话时：直接输出自然语言回复。
- 需要调工具时：**只输出工具调用，不带任何文字**。
- 工具返回结果后：直接生成语义化回答（见第二阶段），不要返回原始 JSON，不要提及"已调用工具"这一过程。
"""


# ===== Graph Nodes =====

async def call_model(state, config: RunnableConfig):
    """异步调用 LLM，返回最终消息。

    必须显式接收并透传 config：LangGraph 在 Python < 3.11 下不会通过
    contextvar 把 StreamMessagesHandler 回调传播进节点，模型调用若不传
    config 就拿不到 token 级回调，stream_mode="messages" 只会下发整条
    AIMessage。
    """
    has_file = state.get("file_source") is not None
    file_info = ""
    if has_file:
        fs = state["file_source"]
        file_info = f"\n\n# 文件状态\n用户已上传文件：{fs.get('suffix', '')} 格式 (id: {fs.get('file_id', '')})。**无论用户说什么（包括'看看''这个''分析一下'等简略表达），只要当前对话里有文件，就必须调 use_legal_agent 处理。**"
    else:
        file_info = "\n\n# 文件状态\n用户未上传任何文件。"

    messages = [SystemMessage(content=llm_prompt + file_info)]
    for m in state["messages"]:
        # 把 use_legal_agent 的原始 JSON 整理成可读文本，避免路由模型原样回显
        if isinstance(m, ToolMessage) and m.name == "use_legal_agent":
            m = ToolMessage(
                content=_clean_legal_tool_result(m.content),
                name=m.name,
                tool_call_id=m.tool_call_id,
            )
        messages.append(m)

    full_content = ""
    tool_call_chunks_acc = []
    response_id = None

    async for chunk in model.astream(messages, config):
        # 记录模型响应 id，最终消息与 token 分片共享同一 id，用于流式去重
        if response_id is None and getattr(chunk, "id", None):
            response_id = chunk.id
        if isinstance(chunk.content, str) and chunk.content:
            full_content += chunk.content
        # 收集 tool call 分片（最终组装成完整 tool_calls）
        if chunk.tool_call_chunks:
            tool_call_chunks_acc.extend(chunk.tool_call_chunks)

    final_id = response_id or str(uuid.uuid4())

    if tool_call_chunks_acc:
        merged = {}
        for tcc in tool_call_chunks_acc:
            idx = tcc.get("index", 0)
            if idx not in merged:
                merged[idx] = {"name": "", "args": "", "id": ""}
            merged[idx]["name"] += tcc.get("name") or ""
            merged[idx]["args"] += tcc.get("args") or ""
            merged[idx]["id"] += tcc.get("id") or ""

        tool_calls = []
        for idx in sorted(merged.keys()):
            mc = merged[idx]
            try:
                args = json.loads(mc["args"]) if mc["args"] else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"name": mc["name"], "args": args, "id": mc["id"]})

        # 工具调用消息不带任何文字内容，避免"已为您调用XX工具"等寒暄进入历史被回显
        return {
            "messages": [
                AIMessage(content="", tool_calls=tool_calls, id=final_id)
            ]
        }

    return {"messages": [AIMessage(content=full_content, id=final_id)]}


def should_continue(state):
    """如果模型调用了工具则路由到 tools，否则结束。"""
    messages = state["messages"]
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


def process_legal_result(state):
    """提取法律子智能体返回的产出文件到全局状态中。"""
    messages = state.get("messages", [])
    if not messages:
        return {}

    for msg in reversed(messages):
        if isinstance(msg, ToolMessage) and msg.name == "use_legal_agent":
            content = msg.content
            try:
                result = json.loads(content) if isinstance(content, str) else content
            except (json.JSONDecodeError, TypeError):
                continue

            output_file = result.get("output_file")
            if output_file:
                return {"output_file": output_file}
            break

    return {}


# ===== Build Graph =====

tools = [use_legal_agent, use_finance_agent]
model = MainModel().bind_tools(tools)
checkpointer = BoundedMemorySaver()
tool_node = ToolNode(tools)

multiAgent_flow = StateGraph(GlobalState)
multiAgent_flow.add_node("call_model", call_model)
multiAgent_flow.add_node("tools", tool_node)
multiAgent_flow.add_node("process_legal_result", process_legal_result)

multiAgent_flow.add_edge(START, "call_model")
multiAgent_flow.add_conditional_edges(
    "call_model",
    should_continue,
    {"tools": "tools", END: END},
)
multiAgent_flow.add_edge("tools", "process_legal_result")
multiAgent_flow.add_edge("process_legal_result", "call_model")

multiAgent = multiAgent_flow.compile(
    name="multiAgent",
    checkpointer=checkpointer,
)
