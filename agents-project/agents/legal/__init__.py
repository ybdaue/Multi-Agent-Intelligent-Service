from .subagents.analysize import analyze_document
from .subagents.consultor import consultor
from .subagents.draftor import draft_document_agent
from typing import Annotated, List, Optional, Sequence, Literal, TypedDict, Union
from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from agents.utils.models import MainModel, IntentModel, CompressModel
from langchain_core.messages import (
    ToolMessage,
    SystemMessage,
    HumanMessage,
    AnyMessage,
    AIMessage,
    RemoveMessage,
)
from langchain_core.runnables import RunnableConfig
import inspect
import json
import time
import uuid
from ..utils.checkpoint import create_checkpoint
from ..utils.agent_store import create_agent_store


class FileSource(TypedDict):
    type: Literal["bytes","path","db"]
    suffix: str
    content: Union[str, bytes]
    file_id: str


class State(MessagesState):
    # ===== 用户输入 =====
    userId: int = 0
    user_message: str
    file_source: Optional[FileSource]
    doc_ids: List[str] = Field(default_factory=list)

    # ===== 偏好 =====
    preference: List[str] = Field(default_factory=list)

    # ===== 对话记忆 =====
    summary: str = Field(default="")

    # ===== 流程控制 =====
    step: int = Field(default=0)
    max_step: int = Field(default=10)

    # ===== 任务栈 =====
    primary_intent: Optional[Literal["draft", "analyze", "consult"]] = None
    pending_tasks: List[str] = Field(default_factory=list)
    completed_tasks: List[str] = Field(default_factory=list)
    task_context: dict = Field(default_factory=dict)

    # ===== 产物 =====
    analysis_result: Optional[dict] = None  #文件分析结果
    answer_result: Optional[str]            #法律咨询结果
    output_file: Optional[FileSource]          #输出文件


from .memory import update, load_memory, checkin


def with_retry_and_fallback(primary, fallback, max_retries=2):
    """Wrap a graph node with retry + fallback on exception.

    wrapper 支持 async primary：节点需要透传 config 以让模型调用走流式回调，
    因此 primary 统一以 (state, config) 调用，fallback 仍以 (state, error) 调用。
    """
    async def wrapper(state, config=None):
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                result = primary(state, config)
                if inspect.isawaitable(result):
                    result = await result
                return result
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    time.sleep(1)
                    continue
        return fallback(state, last_error)
    return wrapper


legal_workflow = StateGraph(state_schema=State)
legal_tools = [analyze_document, consultor, draft_document_agent]
model = MainModel(temperature=0.1).bind_tools(legal_tools)
Intent_model = IntentModel(temperature=0.1)
checkpointer = create_checkpoint("legal_agent")
store = create_agent_store("legal_agent")

from ..utils.parse import parse_and_chunk
from ..utils.RAG import upsert_chunks, delete_expired_chunks, get_chunk_num, FILE_TTL_SECONDS
from langgraph.types import Command



def preprocessing(state: State) -> dict:
    print("正在预处理")
    file_source = state.get("file_source")
    if not file_source:
        # 本轮无文件：清空历史 doc_ids，不保留已有文档引用
        return {"doc_ids": []}

    # 惰性 TTL 清扫：上传前先清掉过期切片，控制向量库总量
    try:
        delete_expired_chunks(time.time() - FILE_TTL_SECONDS)
    except Exception:
        pass

    # 内容哈希查重：TTL 清扫后仍能查到该 file_id 的切片，说明是同一文件且切片未过期，直接复用
    if get_chunk_num(file_source["file_id"]) > 0:
        return {"doc_ids": [file_source["file_id"]], "error": None}

    try:
        chunks = parse_and_chunk(file_source)
    except Exception as e:
        return Command(
            update={
                "error": f"文件解析异常: {e}",
                "messages": [
                    AIMessage(content=f"抱歉，文件解析失败：{e}")
                ],
                "doc_ids": [],
            },
            goto=END,
        )

    if not chunks:
        return Command(
            update={
                "error": "文件解析失败，可能是扫描版 PDF",
                "messages": [
                    AIMessage(content="抱歉，文件解析失败，上传文件格式有误。")
                ],
                "doc_ids": [],
                "chunk_count": 0,
            },
            goto=END
        )

    success = upsert_chunks(chunks)
    if not success:
        return Command(
            update={
                "error": "向量数据库写入失败",
                "messages": [
                    AIMessage(content="抱歉，向量数据库写入失败，请联系管理员。")
                ],
                "doc_ids": [],
                "chunk_count": 0,
            },
            goto=END
        )

    return {
        "doc_ids": [chunks[0]["metadata"]["file_id"]],
        "error": None,
    }

Intent_prompt = """你是一个法律需求解析器。

请从用户消息中提取以下信息，并以严格 JSON 格式输出，禁止输出任何其他文字。

# 字段定义

1. primary_intent（必填，四选一）
   - "draft"：用户最终目标是生成文书（合同、律师函、起诉状等）
   - "analyze"：用户最终目标是审查/分析已有文件或法律文本
   - "consult"：用户最终目标是询问法律概念、法条或建议
   - "chat"：日常对话/无法律任务。涵盖问候、感谢、确认、寒暄闲聊、与法律无关的日常问题，以及元对话——询问助手身份/能力/收费/用法等（"你能做什么""你会写合同吗""你收费吗"）。此时没有要执行的法律任务，pending_tasks 为 []。

2. pending_tasks（必填，按逻辑顺序排列，可为空数组 []）
   可选值：
   - "analyze_file"：分析上传的文件
   - "explain_concept"：解释某个法律概念
   - "draft_document"：起草法律文书
   （chat 意图时此字段为 []）

3. task_context（可选）
   - concept_to_explain：如果用户要求解释某个概念，写出具体名称

# 判定规则
1. 如果同时包含"起草文书"和"分析文件"，primary_intent 选 "draft"。
2. 如果同时包含"分析文件"和"解释概念"，且无起草需求，选 "analyze"。
3. 如果只有咨询问题，选 "consult"。
4. 如果无法归入 draft / analyze / consult 中任何一个（如问候、感谢、确认、闲聊），选 "chat"，pending_tasks 为 []。
5. 如果 analyze_file 和 draft_document 都在 tasks 中，analyze_file 必须在 draft_document 前面。
6. 不要遗漏任何隐性需求。
7. 【上下文优先】识别时必须结合下方提供的"文件状态"和"对话历史"：
   - 用户已上传文件，且当前消息是"分析一下""看看""这个""帮我看看""它""上面说的"等模糊表达时，明确指向已上传文件 → primary_intent="analyze"，pending_tasks=["analyze_file"]。
   - 消息含代词（它/这个/上面/该文件）时，必须结合对话历史还原指代对象后再判断意图。
   - 若当前消息是纯问候/感谢/闲聊，或明确咨询法律概念（如"什么是违约金"），即使已上传文件也按 chat/consult 处理，不强行绑定文件。
8. 【不要过度归类】只有用户确实要求"起草/生成文书""分析/审查文件或文本""查询法律概念/规定"时才选对应意图；若只是询问助手能力/收费/能做什么（"你会写合同吗""你能做什么"），或明显与法律无关的日常话题（天气、笑话、闲聊、情绪宣泄），一律判 chat 且 pending_tasks 为 []。绝不因为消息里出现"合同/写/律师"等词，就把能力咨询或闲聊当成 draft/consult。
9. 拿不准、或消息含义模糊且没有明确法律诉求时，优先 chat/consult，不要臆造起草或分析任务。
10. 只有消息含"帮我起草/生成/审查……"这类明确祈使并给出对象时，才选 draft/analyze；仅出现"合同""起诉"等名词不足以判起草/审查。

# 输出格式（严格 JSON，禁止解释）
{
  "primary_intent": "draft | analyze | consult | chat",
  "pending_tasks": ["analyze_file", "explain_concept", "draft_document"] 或 [],
  "task_context": {
    "concept_to_explain": "概念名称（如有）"
  }
}

# 示例

用户：帮我分析这份文档，告诉我什么是拆迁补偿，再帮我生成一份财产分割合同

输出：
{
  "primary_intent": "draft",
  "pending_tasks": ["analyze_file", "explain_concept", "draft_document"],
  "task_context": {
    "concept_to_explain": "拆迁补偿"
  }
}

用户：这份合同有没有风险

输出：
{
  "primary_intent": "analyze",
  "pending_tasks": ["analyze_file"],
  "task_context": {}
}

用户：你好

输出：
{
  "primary_intent": "chat",
  "pending_tasks": [],
  "task_context": {}
}

用户：帮我生成一份合同

输出：
{
  "primary_intent": "draft",
  "pending_tasks": ["draft_document"],
  "task_context": {}
}

# 更多日常对话示例（能力咨询 / 闲聊 / 与法律无关 → 一律 chat，任务是 []）

用户：你是做什么的？

输出：
{
  "primary_intent": "chat",
  "pending_tasks": [],
  "task_context": {}
}

用户：你会写合同吗？你收费吗？

输出：
{
  "primary_intent": "chat",
  "pending_tasks": [],
  "task_context": {}
}

用户：帮我写一份劳动合同 → 明确祈使委托，才是 draft

输出：
{
  "primary_intent": "draft",
  "pending_tasks": ["draft_document"],
  "task_context": {}
}

用户：讲个笑话吧

输出：
{
  "primary_intent": "chat",
  "pending_tasks": [],
  "task_context": {}
}

# 以下示例包含"文件状态"上下文（用户已上传文件）

文件状态：用户已上传文件
用户：分析一下

输出：
{
  "primary_intent": "analyze",
  "pending_tasks": ["analyze_file"],
  "task_context": {}
}

文件状态：用户已上传文件
用户：这个合法吗

输出：
{
  "primary_intent": "analyze",
  "pending_tasks": ["analyze_file"],
  "task_context": {}
}

# 以下示例包含"对话历史"上下文

对话历史：
用户：帮我生成一份劳动仲裁申请书
助手：已为您生成申请书，请查收下载链接。

用户：再改一下违约金条款

输出：
{
  "primary_intent": "draft",
  "pending_tasks": ["draft_document"],
  "task_context": {}
}
"""
def _intent_node(state, config=None):
    user_msg = state["user_message"]

    # ===== 组装对话上下文：文件状态 + 对话历史 =====
    has_file = state.get("file_source") is not None or bool(state.get("doc_ids"))
    file_status = "用户已上传文件（可对其进行分析/审查）" if has_file else "用户未上传文件"

    all_messages = state.get("messages", [])
    conv_lines = []
    for m in all_messages:
        if isinstance(m, HumanMessage):
            conv_lines.append(f"用户：{m.content}")
        elif isinstance(m, AIMessage) and not (hasattr(m, "tool_calls") and m.tool_calls):
            if m.content:
                conv_lines.append(f"助手：{m.content}")
    history_str = "\n".join(conv_lines[:-1]) if len(conv_lines) > 1 else "（无历史）"
    summary = (state.get("summary") or "").strip()
    if summary:
        history_str = f"【更早对话摘要】\n{summary}\n\n{history_str}"

    system_content = f"""{Intent_prompt}
        # 当前对话上下文（识别意图时必须结合）
        文件状态：{file_status}
        对话历史（最新在最后）：
        {history_str}"""

    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=user_msg),
    ]
    # disable_streaming：意图 JSON 只用于内部路由，不进客户端 SSE 流
    response = Intent_model.invoke(messages, {"disable_streaming": True})
    try:
        parsed = json.loads(response.content)
        print("识别到用户意图",user_msg,parsed)
    except json.JSONDecodeError:
        parsed = rule_based_fallback(user_msg, has_file=has_file)
    return {
        "primary_intent": parsed.get("primary_intent"),
        "pending_tasks": parsed.get("pending_tasks", []),
        "task_context": parsed.get("task_context", {}),
        "trace_id": str(uuid.uuid4()),
        "step": 0,
        "completed_tasks": [],
    }


def _intent_fallback(state, error=None):
    return Command(
        update={
            "error": f"意图识别服务不可用：{error}",
            "messages": [AIMessage(content="抱歉，意图识别服务暂时不可用，请稍后再试。")],
        },
        goto=END
    )
# 兜底函数，防止意图识别失败
def rule_based_fallback(msg: str, has_file: bool = False) -> dict:
    """LLM 解析失败时的兜底规则"""
    msg_lower = msg.lower().strip()

    # --- 优先级 1：文件优先（已上传文件 + 模糊指向文件的表达） ---
    if has_file:
        file_ref_keywords = ["分析", "审查", "看看", "检查", "风险", "审核", "改一下", "修改", "这个", "它", "上面", "该", "此"]
        consult_ref_keywords = ["什么是", "什么叫", "解释"]
        if any(k in msg_lower for k in file_ref_keywords) and not any(k in msg_lower for k in consult_ref_keywords):
            # 已有文件 + 修改/起草类表达 → 基于文件起草/修改，而非分析
            draft_keywords = ["修改", "改一下", "起草", "生成", "重写", "变更"]
            if any(k in msg_lower for k in draft_keywords):
                return {
                    "primary_intent": "draft",
                    "pending_tasks": ["draft_document"],
                    "task_context": {},
                }
            return {
                "primary_intent": "analyze",
                "pending_tasks": ["analyze_file"],
                "task_context": {},
            }

    # --- 优先级 2：起草类 ---
    draft_keywords = ["写", "起草", "生成", "拟一份", "拟个", "律师函", "合同", "协议", "起诉状", "上诉状"]
    if any(k in msg_lower for k in draft_keywords):
        tasks = []
        analyze_keywords = ["分析", "审查", "看看", "检查", "风险"]
        if any(k in msg_lower for k in analyze_keywords):
            tasks.append("analyze_file")
        tasks.append("draft_document")
        return {
            "primary_intent": "draft",
            "pending_tasks": tasks,
            "task_context": {},
        }

    # --- 优先级 3：分析类 ---
    analyze_keywords = ["分析", "审查", "风险", "看", "审核", "改一下", "修改"]
    if any(k in msg_lower for k in analyze_keywords):
        return {
            "primary_intent": "analyze",
            "pending_tasks": ["analyze_file"],
            "task_context": {},
        }

    # --- 优先级 4：纯咨询 ---
    consult_keywords = [
        "什么是", "什么叫", "解释", "区别", "规定", "法条", "法律",
        "怎么办", "怎么", "如何", "违法", "犯法", "犯罪", "拖欠", "欠钱",
        "赔偿", "赔付", "离婚", "起诉", "诉讼", "赔偿多少", "是否合法",
    ]
    concept = ""
    for k in consult_keywords:
        if k in msg_lower:
            idx = msg_lower.index(k) + len(k)
            concept = msg[idx:idx + 10].strip("？??。，,！!")
            break

    if concept or any(k in msg_lower for k in consult_keywords):
        return {
            "primary_intent": "consult",
            "pending_tasks": ["explain_concept"],
            "task_context": {"concept_to_explain": concept} if concept else {},
        }

    # --- 兜底：没有任何法律信号 → 当作日常对话，不要硬造咨询/起草任务 ---
    return {
        "primary_intent": "chat",
        "pending_tasks": [],
        "task_context": {},
    }


decision_prompt = """你是法律助手的核心调度 Agent。

你的职责：根据任务栈，按顺序调用子 Agent 工具完成任务。

# 当前状态
- 用户消息：{last_user_message}
- 近期对话历史（最新在最后）：
{conversation_history}
- 法律领域偏好：{legal_domain}
- 任务上下文：{task_context}
- 当前步骤：{step} / {max_step}
- 待办任务栈：{pending_tasks}
- 已完成任务：{completed_tasks}
- 剩余任务：{remaining_tasks}
- 下一步必须完成：{next_task}
  · 文件解析：{file_status}
  · 已解析文件ID：{doc_id}
  · 分析结果：{analysis_status}
  · 文书草稿：{draft_status}
  · 文书路径：{output_file_path}

# 可调用的子 Agent 工具
1. analyze_document —— 分析已有文件，返回风险报告
   - file_id：填入上面的"已解析文件ID"
2. draft_document_agent —— 起草/修改法律文书，返回 .docx 路径
   - 初次生成：填 doc_type + requirement，不填 original_file_id
   - 基于上传文件修改/起草：把上面"已解析文件ID"填入 original_file_id，具体修改/起草需求填
     revision_instructions（用户说"修改我上传的合同""基于这份文件生成XX"时必须传）
   - 该工具内部会自行检索相关法律法规作为起草依据，无需配合任何验证工具
3. consultor —— 解释法律概念
   - question：不能直接传用户的原始消息。你需要结合近期对话历史、用户当前问题、任务上下文、
     法律领域偏好、以及前面步骤的分析结果（如有），推测用户真正想了解的法律问题，将其重新组织成
     一个完整、具体、自包含的法律咨询问题再传入。
     · ⚠️ 指代消解：如果用户说"这个税""那个条款""上面说的"等代词，必须根据对话历史还原具体指代。
       例如对话历史: "什么是车辆购置税" → 当前: "这个税怎么计算" → 应传"车辆购置税的计算方式是
       什么？计税依据和税率是多少？"
     · 用户问"这个条款有问题吗" + 分析结果中有违约金相关风险 → 应传"用户合同中第X条违约金条款
       是否存在法律风险？违约金过高在法律上如何认定？"
     · 用户问"什么是不可抗力" + 领域偏好为合同法 → 应传"在合同法中，不可抗力的法律定义是什么？
       不可抗力条款在合同中如何适用？"
     · 任务上下文中有 concept_to_explain → 将其作为问题核心，结合用户消息展开

# 执行规则

## 顺序
- 每轮只做"下一步必须完成"的任务，调用其对应的工具；该任务完成后会从"剩余任务"移入"已完成任务"。
- 任务与工具映射：analyze_file→analyze_document；explain_concept→consultor；draft_document→draft_document_agent
- 严禁重复执行"已完成任务"中的任务（如已分析完文件，就不要再调用 analyze_document）
- 每轮只调用一个工具，不要在同一轮内并行调用多个工具

## 状态行与重复判定
- "文件解析/已解析文件ID/分析结果/文书草稿/文书路径"等状态行只是历史产物提示，表示此前是否产生过结果，**不代表本轮任务已完成**。
- 判断"是否已做"的唯一依据是"已完成任务"列表（仅本轮内）。
- 用户明确要求"重新分析/再分析/再生成"时，即使状态行显示已有结果，也必须按"下一步必须完成"重新调用对应工具，不得跳过。

# 完成判定
- "剩余任务"为空后，不要再调用任何工具，直接输出总结结束。
- 当前步骤已达上限时，立即停止，不要再调用工具。

# 输出
- 所有输出必须使用中文。
- 每轮只需调用下一个待办工具，调用工具时不要输出自然语言总结或解释。
- 全部任务完成后，输出 1~2 句简短的中文总结，然后结束。
"""


TOOL_TO_TASK = {
    "analyze_document": "analyze_file",
    "consultor": "explain_concept",
    "draft_document_agent": "draft_document",
}


def extract_tool_results(state: State) -> dict:
    """提取最近一次工具执行结果到 state 产物字段中。"""
    messages = state.get("messages", [])
    if not messages:
        return {}

    last_msg = messages[-1]
    if not isinstance(last_msg, ToolMessage):
        return {}

    updates = {}
    try:
        if last_msg.name == "analyze_document":
            content = last_msg.content
            result = json.loads(content) if isinstance(content, str) else content
            updates["analysis_result"] = result

        elif last_msg.name == "consultor":
            updates["answer_result"] = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)

        elif last_msg.name == "draft_document_agent":
            file_path = last_msg.content
            if isinstance(file_path, str) and file_path.strip().endswith(".docx"):
                updates["output_file"] = {
                    "type": "path",
                    "suffix": ".docx",
                    "content": file_path,
                    "file_id": f"output_{uuid.uuid4().hex[:8]}",
                }

    except (json.JSONDecodeError, TypeError, AttributeError):
        pass

    return updates


async def _astream_assistant_response(llm, messages, config):
    """流式累积 LLM 输出为完整 AIMessage（含 tool_calls）。

    config 必须透传给 llm.astream：由 graph 运行上下文把 token 回调灌进本次调用，
    从而让外部 .astream(stream_mode="messages") 能逐 token 拿到内容。
    """
    full_content = ""
    tool_call_chunks_acc = []
    response_id = None

    async for chunk in llm.astream(messages, config):
        if response_id is None and getattr(chunk, "id", None):
            response_id = chunk.id
        if isinstance(chunk.content, str) and chunk.content:
            full_content += chunk.content
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
        return AIMessage(content="", tool_calls=tool_calls, id=final_id)

    return AIMessage(content=full_content, id=final_id)


_CHAT_PERSONA = """你是一位中文友好的 AI 法律助手。用户当前只是在日常对话（问候、寒暄、闲聊），或询问关于你自身的问题，本轮不需要起草文书、审查文件或检索法条。

请自然作答：
1. 语气亲切、口语化，2~4 句即可；不要使用"已调用工具""任务已完成""风险报告"之类的系统口吻，也不要输出 JSON。
2. 若问你是谁或能做什么：说明你主要擅长——法律文书起草与修改（合同、起诉状、律师函等）、上传文件的法律风险审查、法律概念与法条咨询；并引导用户用一句话说清需求，或上传要审查的文件。
3. 若聊到与法律无关的日常话题，按通识友好回应即可，不必硬扯法律。
4. 若用户其实提出了明确的法律任务（起草/审查/咨询），用一句话请他把需求说具体些，再转入对应服务。
5. 全程中文，简洁。

# 最近对话（供语气与指代参考，不要复述）
{history}
"""


async def _casual_answer(state, config):
    """无待办任务的闲聊/元对话轮次：走轻量直答，不接法律调度器、不绑定工具。"""
    conv_lines = []
    for m in state.get("messages", []):
        if isinstance(m, HumanMessage):
            conv_lines.append(f"用户：{m.content}")
        elif isinstance(m, AIMessage) and not (hasattr(m, "tool_calls") and m.tool_calls):
            if m.content:
                conv_lines.append(f"助手：{m.content}")
    history = "\n".join(conv_lines[:-1]) if len(conv_lines) > 1 else "（无历史）"
    summary = (state.get("summary") or "").strip()
    if summary:
        history = f"【更早对话摘要】{summary}\n\n{history}"

    chat_llm = MainModel(temperature=0.5)
    messages = [
        SystemMessage(content=_CHAT_PERSONA.format(history=history)),
        HumanMessage(content=state["user_message"]),
    ]
    response = await _astream_assistant_response(chat_llm, messages, config)
    return {
        "messages": [response],
        "step": state.get("step", 0),
        "completed_tasks": state.get("completed_tasks", []),
    }


async def _assistant_node(state, config=None):
    print("法律assistant正在工作")
    # 提取最近一次工具执行结果到产物字段（会合并到返回值中）
    tool_result_updates = extract_tool_results(state)

    # 根据"本轮"最近执行的工具推导"已完成任务"：只认本轮（最后一条 HumanMessage 之后）
    # 产生的 ToolMessage，避免历史轮次的工具调用污染本轮的 completed_tasks
    all_msgs = state.get("messages", [])
    scan_from = 0
    for i in range(len(all_msgs) - 1, -1, -1):
        if isinstance(all_msgs[i], HumanMessage):
            scan_from = i + 1
            break
    completed_tasks = list(state.get("completed_tasks", []))
    last_tool_name = None
    for msg in reversed(all_msgs[scan_from:]):
        if isinstance(msg, ToolMessage) and msg.name in TOOL_TO_TASK:
            last_tool_name = msg.name
            break
    if last_tool_name:
        done_task = TOOL_TO_TASK[last_tool_name]
        if done_task not in completed_tasks:
            completed_tasks.append(done_task)

    pending_tasks = state.get("pending_tasks", [])
    remaining_tasks = [t for t in pending_tasks if t not in completed_tasks]
    next_task = remaining_tasks[0] if remaining_tasks else None

    print(f"[assistant] 已完成={completed_tasks} 剩余={remaining_tasks} 下一步={next_task} 最后工具={last_tool_name}")

    # 纯聊天/无待办任务轮次：不走法律调度器与工具，直接轻量作答（闲聊更快、语气自然、不会误调工具）
    if not pending_tasks:
        return await _casual_answer(state, config)

    # 计算各产物状态文本
    file_status = "有" if (state.get("file_source") is not None or state.get("doc_ids")) else "无"
    has_analysis = tool_result_updates.get("analysis_result", state.get("analysis_result")) is not None
    analysis_status = "有" if has_analysis else "无"

    doc_ids = state.get("doc_ids", [])
    doc_id = doc_ids[0] if doc_ids else ""

    current_output_file = tool_result_updates.get("output_file", state.get("output_file"))
    draft_status = "有" if current_output_file else "无"
    output_file_path = current_output_file.get("content", "") if current_output_file else ""

    task_context = state.get("task_context", {})
    task_context_str = json.dumps(task_context, ensure_ascii=False) if task_context else "无"

    # 从 checkpoint 持久化的 state["messages"] 中提取用户可见对话历史，用于指代消解
    all_messages = state.get("messages", [])
    conversation_pairs = []
    for msg in all_messages:
        if isinstance(msg, HumanMessage):
            conversation_pairs.append(f"用户：{msg.content}")
        elif isinstance(msg, AIMessage) and not (hasattr(msg, "tool_calls") and msg.tool_calls):
            if msg.content:
                conversation_pairs.append(f"助手：{msg.content}")

    # 最后一条 HumanMessage 是当前轮次，往前都是历史
    conversation_history_str = "\n".join(conversation_pairs[:-1]) if len(conversation_pairs) > 1 else "（无历史）"
    summary = (state.get("summary") or "").strip()
    if summary:
        conversation_history_str = f"【更早对话摘要】\n{summary}\n\n{conversation_history_str}"

    system_prompt = decision_prompt.format(
        last_user_message=state["user_message"],
        conversation_history=conversation_history_str,
        legal_domain="、".join(state.get("preference", [])) or "通用民事",
        task_context=task_context_str,
        step=state.get("step", 0),
        max_step=state.get("max_step", 10),
        pending_tasks=pending_tasks,
        completed_tasks=completed_tasks,
        remaining_tasks=remaining_tasks,
        next_task=next_task,
        doc_id=doc_id,
        file_status=file_status,
        analysis_status=analysis_status,
        draft_status=draft_status,
        output_file_path=output_file_path,
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=state["user_message"]),
    ]

    # ===== 硬停止：防止 assistant↔child_agent 无限循环 =====
    # 任务栈耗尽或总步骤超限时，不再调用模型，直接产出最终消息结束。
    step = state.get("step", 0)
    max_step = state.get("max_step", 10)

    tasks_done = bool(pending_tasks) and next_task is None
    if step >= max_step:
        stop_reason = "step"
    elif tasks_done:
        stop_reason = "done"
    else:
        stop_reason = None

    if stop_reason:
        if stop_reason == "done" and output_file_path:
            final_msg = f"任务已完成，已生成文书：{output_file_path}"
        elif stop_reason == "done":
            final_msg = "本轮任务已完成。"
        else:
            final_msg = "本轮处理步骤已达上限，为避免重复处理已自动结束。"
        # 显式分配 id：produce_summary 模式下 summary 节点按 id 移除本条简短的终稿
        return {
            "messages": [AIMessage(content=final_msg, id=str(uuid.uuid4()))],
            "step": step,
            "completed_tasks": completed_tasks,
            **tool_result_updates,
        }

    response = await _astream_assistant_response(model, messages, config)

    # 强制每轮只调一个工具：并行调用会破坏任务先后依赖，只保留第一个，剩余丢弃
    if hasattr(response, "tool_calls") and len(response.tool_calls) > 1:
        response = AIMessage(
            content=response.content,
            tool_calls=[response.tool_calls[0]],
            id=response.id,
        )

    # 模型若试图重复执行已完成的任务，重罚 step 加快触顶兜底（正常模型不应走到这里）
    repeated = False
    if hasattr(response, "tool_calls") and response.tool_calls:
        tool_name = response.tool_calls[0].get("name") or response.tool_calls[0]["name"]
        if TOOL_TO_TASK.get(tool_name) in completed_tasks:
            repeated = True

    tool_count = 1 if (hasattr(response, "tool_calls") and response.tool_calls) else 0
    return {
        "messages": [response],
        "step": step + (2 if repeated else tool_count),
        "completed_tasks": completed_tasks,
        **tool_result_updates,
    }


def _assistant_fallback(state, error=None):
    tool_result_updates = extract_tool_results(state)
    return Command(
        update={
            "error": f"调度模型服务不可用：{error}",
            "messages": [AIMessage(content="抱歉，服务暂时不可用，请稍后再试。")],
            **tool_result_updates,
        },
        goto=END
    )


_summarizer_model = CompressModel(temperature=0.2)


def _render_results_text(state: State) -> str:
    """把本轮任务产物整理成可读文本，供 summary 节点生成最终答复。"""
    parts = []

    analysis = state.get("analysis_result")
    if analysis:
        if isinstance(analysis, dict):
            risks = analysis.get("risks") or []
            if risks:
                lines = ["【文件风险分析结论】"]
                for r in risks:
                    line = f"- [{r.get('risk_level', '')}] {r.get('issue', '')}"
                    if r.get("suggestion"):
                        line += f"（建议：{r['suggestion']}）"
                    if r.get("legal_basis"):
                        line += f"（依据：{r['legal_basis']}）"
                    lines.append(line)
                parts.append("\n".join(lines))
            elif analysis.get("summary"):
                parts.append(f"【文件风险分析结论】{analysis['summary']}")
        else:
            parts.append(f"【文件风险分析结论】{analysis}")

    answer = state.get("answer_result")
    if answer:
        parts.append(f"【法律咨询答复】\n{answer}")

    of = state.get("output_file")
    if isinstance(of, dict) and of.get("content"):
        path = str(of["content"])
        if path:
            fname = path.replace("\\", "/").rsplit("/", 1)[-1]
            parts.append(f"【已生成文书】{fname}（请点击下载）")

    return "\n\n".join(parts)


_SUMMARY_PROMPT = """你是法律助手的最终总结。请根据下面的"用户提问"与"本轮产物"，生成一段面向用户的完整、连贯的最终答复（中文）。

# 要求
1. 直接给结论：说清本轮完成了什么（法律咨询结论 / 文件风险分析与建议 / 起草或修改了什么文书及其用途），涉及文件时用真实文件名交代。
2. 不要复述"我调用了哪个工具"之类的过程，不要出现 JSON、字段名或风险等级符号。
3. 若本轮是咨询，把专业解答讲清楚；若分析了文件，概括整体风险水平与主要建议；若起草/修改了文书，说明文书要点与下载方式。
4. 字数 200~600 字，纯文本、条目式即可。

# 用户提问
{user_message}

# 本轮产物
{result_text}

# 对话（供参考）
{conversation}

请输出最终答复："""


async def _summary_node(state: State, config: RunnableConfig):
    """任务跑完后的收尾：用 CompressModel 生成一段完整最终答复（流式）。

    produce_summary 未开启（如 multiAgent 以子图方式调用本图）时不做总结，
    返回空更新原样保留 assistant 的答复，保证既有行为不变。
    """
    if not bool((config or {}).get("configurable", {}).get("produce_summary")):
        return {}
    if not (
        state.get("completed_tasks")
        or any(
            state.get(k) is not None
            for k in ("analysis_result", "answer_result", "output_file")
        )
    ):
        # 纯闲聊等无产物轮次：不额外调用总结模型，assistant 答复即最终答复
        return {}

    # 定位本轮终稿（最后一条无 tool_calls 的 AIMessage），生成总结后把它替换掉，
    # 避免"简短完成语 + 完整总结"重复入库/重复展示。
    target_id = None
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            target_id = msg.id
            break

    conv_lines = []
    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            conv_lines.append(f"用户：{msg.content}")
        elif isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            if msg.content:
                conv_lines.append(f"助手：{msg.content}")

    prompt = _SUMMARY_PROMPT.format(
        user_message=state.get("user_message", ""),
        result_text=_render_results_text(state) or "（无）",
        conversation="\n".join(conv_lines) or "（无）",
    )

    summary_text = ""
    async for chunk in _summarizer_model.astream(
        [SystemMessage(content=prompt)], config
    ):
        if isinstance(chunk.content, str) and chunk.content:
            summary_text += chunk.content
    summary_text = summary_text.strip() or "本轮任务已完成。"

    updates = []
    if target_id:
        updates.append(RemoveMessage(id=target_id))
    updates.append(AIMessage(content=summary_text, id=str(uuid.uuid4())))
    return {"messages": updates}


def _summary_fallback(state, error=None):
    # 总结失败则保留 assistant 原答复，不阻塞会话
    print(f"[summary] 生成总结失败，保留原答复：{error}")
    return {}


legal_tool_node = ToolNode(legal_tools)


def use_child_agent(state: State):
    latest_message = state["messages"][-1]
    print("正在判断是否需要调用工具",latest_message)
    if isinstance(latest_message, AIMessage) and latest_message.tool_calls:
        return "child_agent"
    # 无工具调用即进入终局：由 summary 节点决定是否需要生成最终总结（produce_summary），
    # 否则为空操作直接落到 update。
    return "summary"


legal_workflow.add_node("checkin", checkin)
legal_workflow.add_node("preprocessing",preprocessing)
legal_workflow.add_node("Intent",with_retry_and_fallback(_intent_node, _intent_fallback))
legal_workflow.add_node("load_memory",load_memory)
legal_workflow.add_node("assistant",with_retry_and_fallback(_assistant_node, _assistant_fallback))
legal_workflow.add_node("child_agent",legal_tool_node)
legal_workflow.add_node("summary",with_retry_and_fallback(_summary_node, _summary_fallback))
legal_workflow.add_node("update",update)

# checkin 先落库本轮提问/会话行，再进入 preprocessing；即便 preprocessing 解析失败
# 早退到 END，提问也已保存。
legal_workflow.add_edge(START,"checkin")
legal_workflow.add_edge("checkin","preprocessing")
legal_workflow.add_edge("preprocessing","Intent")
# legal_workflow.add_edge("Intent",END)
legal_workflow.add_edge("Intent","load_memory")
legal_workflow.add_edge("load_memory","assistant")
legal_workflow.add_conditional_edges(
    "assistant",
    use_child_agent,
    {
        "summary":"summary",
        "child_agent":"child_agent"
    },
)
legal_workflow.add_edge("child_agent","assistant")
legal_workflow.add_edge("summary","update")
legal_workflow.add_edge("update",END)

legal_agent = legal_workflow.compile(name="legal_agent", checkpointer=checkpointer, store=store)
