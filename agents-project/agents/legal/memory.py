from langgraph.store.base import BaseStore
from . import State
from agents.utils.models import CompressModel, IntentModel
from pydantic import BaseModel, Field
from typing import List
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, RemoveMessage
from langgraph.config import get_config
import hashlib
import json
import os
import time
import uuid

# 每个用户线程只保留最近多少轮完整问答，更早的折叠进 summary
RECENT_ROUNDS = 5


def load_memory(state: State, store: BaseStore):
    """从长期 store 读用户画像，从 state 读已持久化的对话摘要 summary。"""
    user_id = str(state.get("userId", 0))
    namespace = ('memory', user_id)
    existing_memory = store.get(namespace, "user_memory")
    preference = []
    if existing_memory and existing_memory.value:
        data = existing_memory.value
        profile = data.get('preference') if isinstance(data, dict) else data
        preference = profile.get('legal_preference', []) if isinstance(profile, dict) else getattr(profile, 'legal_preference', [])
    return {"preference": preference, "summary": state.get("summary") or ""}


class OutPut(BaseModel):
    user_id: str = Field(
        default="",
        description="用户的Id"
    )
    legal_preference: List[str] = Field(
        default_factory=lambda: ["通用民事"],
        description="用户关注的法律领域列表，按关注度从高到低排序，最多5个"
    )


profile_prompt = """
你是一个法律用户画像分析器。

你的唯一任务是：根据用户对话，更新其关注的**法律领域列表**。
输出必须是 JSON，且 legal_preference 永远是一个字符串数组。

# 可选法律领域（仅限以下枚举）
合同纠纷、劳动争议、婚姻家庭、知识产权、公司治理、
刑事辩护、房产土地、侵权责任、金融证券、通用民事

# 更新规则
1. 优先依据用户最新发言判断。
2. 如果用户明确提及某领域（如“劳动合同”“离婚”“专利”），将该领域**插入数组首位**。
3. 如果用户问题描述符合某领域常识（如“被辞退赔偿”“彩礼返还”），同样将其置顶。
4. 如果用户同时涉及多个领域，选择**最核心、最紧急**的一个置顶，其余保留。
5. 如果用户问题不涉及法律或无法判断，数组仅保留["通用民事"]。
6. 如果用户只是打招呼、感谢、无关闲聊，**原样返回现有数组，不做任何修改**。
7. 数组按“关注度从高到低”排序。
8. 数组长度不超过 5 个，超出时丢弃最末位的旧领域。

# 当前已知用户偏好
{existing_domain}

# 最近对话
{conversation}

# 输出格式（必须遵守）
{{
  "legal_preference": ["领域1", "领域2", ...]
}}

# 示例
当前偏好：["合同纠纷"]
用户输入：公司拖欠工资怎么办
输出：
{{"legal_preference": ["劳动争议", "合同纠纷"]}}

当前偏好：["劳动争议"]
用户输入：谢谢，明白了
输出：
{{"legal_preference": ["劳动争议"]}}

当前偏好：["劳动争议"]
用户输入：房子拆迁怎么补偿
输出：
{{"legal_preference": ["房产土地", "劳动争议"]}}

当前偏好：["通用民事"]
用户输入：今天天气不错
输出：
{{"legal_preference": ["通用民事"]}}
"""


_summary_prompt = """你是一个法律对话记忆压缩器。你的任务是合并“更早摘要”与“本次需要折叠的更早对话”，产出一段简短、连贯的中文历史摘要。

# 规则
1. 合并时保留更早摘要中的既有结论，不重复、不丢信息；本次新增内容只补充更早摘要没覆盖的关键信息。
2. 只记录关键内容：用户的核心诉求、已确认的事实、已给出的法律结论/建议要点、起草/分析/生成过的文书及其去向。
3. 只要提供了【文件记录】，必须原样保留其中“文件信息与位置”，方便后续引用，不得省略。
4. 输出为纯文本、要点式，控制在 200~600 字，不要用 markdown 标题或 JSON。
5. 最近 {recent} 轮对话单独保留在 messages 里，**不要**写入摘要。

输入：
【更早摘要】
{prev_summary}

【本次折叠的更早对话】
{older_text}

【文件记录】
{file_notes}

请输出合并后的历史摘要："""


model = IntentModel(temperature=0.1).with_structured_output(OutPut)
_summarize_model = CompressModel(temperature=0.2)


def _content_of(message) -> str:
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else str(content)


def _split_rounds(messages) -> list:
    """把 messages 切成一轮轮问答。一轮 = 一条用户提问 + 紧随其后的助手最终回答（不含调工具消息）。

    只保留“对话部分”：HumanMessage 与无 tool_calls 的 AIMessage；工具消息/中间调用被跳过。
    """
    rounds = []
    current = None
    for m in messages:
        if isinstance(m, HumanMessage):
            if current is not None:
                rounds.append(current)
            current = {"human": m, "replies": [], "ids": [m.id] if m.id else []}
        elif isinstance(m, AIMessage) and not getattr(m, "tool_calls", None):
            if current is not None and _content_of(m).strip():
                current["replies"].append(m)
                if m.id:
                    current["ids"].append(m.id)
    if current is not None:
        rounds.append(current)
    return rounds


def _round_text(round_: dict) -> str:
    lines = [f"用户：{_content_of(round_['human'])[:800]}"]
    for reply in round_["replies"]:
        content = _content_of(reply)
        if content.strip():
            lines.append(f"助手：{content[:800]}")
    return "\n".join(lines)


def _rounds_text(rounds: list) -> str:
    return "\n\n".join(_round_text(r) for r in rounds)


def _file_notes(state: State) -> str:
    """收集本轮出现的文件信息与位置（用户上传 / 智能体生成）。"""
    notes = []
    file_source = state.get("file_source")
    if file_source:
        suffix = (file_source.get("suffix") or "").strip(".")
        fid = file_source.get("file_id") or ""
        notes.append(
            f"用户上传文件：.{suffix} 格式，file_id={fid}；"
            "位置：已解析入库（RAG 向量库 + temp_file 临时表）"
        )
    output_file = state.get("output_file")
    if output_file and output_file.get("content"):
        path = str(output_file["content"])
        name = os.path.basename(path) if isinstance(path, str) else (output_file.get("suffix") or "文件")
        notes.append(f"智能体生成文件：{name}；位置：{path}")
    return "\n".join(notes)


def _merge_summary(prev_summary: str, older_text: str, file_notes: str) -> str:
    """把更早摘要 + 超出最近5轮的更早轮次（+ 文件记录）合并为新的对话摘要。"""
    if not older_text.strip() and not file_notes.strip():
        return prev_summary
    input_text = (
        f"【更早摘要】\n{prev_summary or '（无）'}\n\n"
        f"【本次折叠的更早对话】\n{older_text.strip() or '（无）'}\n\n"
        f"【文件记录】\n{file_notes.strip() or '（无）'}"
    )
    prompt = SystemMessage(
        content=_summary_prompt.format(
            prev_summary=prev_summary or "（无）",
            older_text=older_text.strip() or "（无）",
            file_notes=file_notes.strip() or "（无）",
            recent=RECENT_ROUNDS,
        )
    )
    try:
        response = _summarize_model.invoke(
            [prompt, HumanMessage(content=input_text)],
            {"disable_streaming": True},
        )
        text = (response.content if isinstance(response.content, str) else str(response.content)).strip()
        return text or prev_summary
    except Exception:
        # 压缩失败静默回退：不丢更早摘要即可
        return prev_summary


# ===== 会话历史持久化（写入 user_session / user_session_history）=====
# 读取端见 api/utils/sessions.py。定位 key 与 checkpoint 完全一致，均取自 graph
# 运行 config：userId / threadId；agent 固定 legal_agent（method.py 查询同名）。
SESSION_AGENT = "legal_agent"


def _stable_message_id(kind: str, content: str) -> str:
    return f"{kind}:{hashlib.sha1(content.encode('utf-8', 'ignore')).hexdigest()[:16]}"


def _round_messages(round_: dict) -> list:
    """把一轮问答（一条用户提问 + 其助手回答）转成可序列化的消息记录。"""
    msgs = []
    human = round_["human"]
    hcontent = _content_of(human)
    if hcontent.strip():
        msgs.append({
            "role": "user",
            "content": hcontent,
            "messageId": human.id or _stable_message_id("user", hcontent),
        })
    for reply in round_["replies"]:
        content = _content_of(reply)
        if content.strip():
            msgs.append({
                "role": "assistant",
                "content": content,
                "messageId": reply.id or _stable_message_id("assistant", content),
            })
    return msgs


def _persist_session(uid: str, tid: str, agent: str, messages: list) -> None:
    """upsert user_session 一行，并把新消息（按 messageId 去重）追加进 history。"""
    if not messages:
        return
    import psycopg

    from api.utils.db import postgreSQL_URL

    title = ""
    for m in messages:
        if m.get("role") == "user" and m.get("content"):
            title = str(m["content"]).strip().replace("\n", " ")[:40]
            break

    with psycopg.connect(postgreSQL_URL) as conn:
        cur = conn.execute(
            'INSERT INTO user_session (id, "userId", "agentName", "threadId", title, "createdAt", "updatedAt") '
            "VALUES (%s, %s, %s, %s, %s, now(), now()) "
            'ON CONFLICT ("userId", "agentName", "threadId") '
            'DO UPDATE SET "updatedAt" = now() RETURNING id',
            (uuid.uuid4().hex, uid, agent, tid, title),
        )
        session_id = cur.fetchone()[0]

        row = conn.execute(
            'SELECT messages FROM user_session_history WHERE "sessionId" = %s',
            (session_id,),
        ).fetchone()
        existing = row[0] if row else None
        if existing is None:
            existing = []
        elif isinstance(existing, str):
            existing = json.loads(existing) if existing else []
        have = {m.get("messageId") for m in existing if m.get("messageId")}
        fresh = [m for m in messages if m.get("messageId") and m["messageId"] not in have]
        if fresh:
            conn.execute(
                'INSERT INTO user_session_history (id, "sessionId", messages, "createdAt", "updatedAt") '
                "VALUES (%s, %s, %s::jsonb, now(), now()) "
                'ON CONFLICT ("sessionId") '
                'DO UPDATE SET messages = EXCLUDED.messages, "updatedAt" = now()',
                (uuid.uuid4().hex, session_id, json.dumps(existing + fresh, ensure_ascii=False)),
            )
        conn.commit()


def checkin(state: State):
    """请求开始即把"本轮用户提问 + 会话行"落库（图首节点）。

    只要请求进入图就先保存提问，后续即使文件解析失败/意图兜底/流被客户端中断
    走到 END 而没跑完 update，会话与提问也不会丢。返回 None，不改动 state。
    """
    try:
        messages = state.get("messages", []) or []
        human = None
        for m in reversed(messages):
            if isinstance(m, HumanMessage) and getattr(m, "id", None) and _content_of(m).strip():
                human = m
                break
        if human is None:
            return None
        cfg = get_config().get("configurable", {})
        uid = cfg.get("userId") if cfg.get("userId") is not None else cfg.get("user_id", "0")
        tid = cfg.get("thread_id")
        if tid:
            _persist_session(
                str(uid), tid, SESSION_AGENT,
                [{
                    "role": "user",
                    "content": _content_of(human),
                    "messageId": human.id,
                }],
            )
    except Exception as e:
        print(f"[memory] checkin 写入失败（已忽略）: {e}")
    return None


def update(state: State, store: BaseStore):
    print("记忆更新中")
    user_id = str(state.get("userId", 0))
    namespace = ("memory", user_id)
    messages = state.get("messages", []) or []

    # ===== 0) 先把本轮问答持久化到 user_session_history，供会话列表/历史读取 =====
    # 放在最前，避免被下面的画像/压缩模型失败提前 return 连带。checkin 已存 user 提问
    # （同一 messageId），此处去重后只新增 assistant 回复。
    rounds = _split_rounds(messages)
    if rounds:
        try:
            cfg = get_config().get("configurable", {})
            uid = cfg.get("userId") if cfg.get("userId") is not None else cfg.get("user_id", "0")
            tid = cfg.get("thread_id")
            if tid:
                _persist_session(str(uid), tid, SESSION_AGENT, _round_messages(rounds[-1]))
        except Exception as e:
            print(f"[memory] 写入会话历史失败（已忽略）: {e}")

    # ===== 1) 用户画像更新（尽力而为，失败不中断收尾）=====
    if messages:
        formatted_memory = state.get("preference", [])
        conversation_text = "\n".join(
            f"{'用户' if isinstance(m, HumanMessage) else 'AI'}: {m.content[:500] if isinstance(m.content, str) else str(m.content)[:500]}"
            for m in messages[-4:]
        )
        formatted_system_message = SystemMessage(
            content=profile_prompt.format(
                conversation=conversation_text,
                existing_domain=formatted_memory,
            )
        )
        user_prompt = HumanMessage(
            content="Please analyze the conversation and update the customer's memory profile according to the instructions."
        )
        updated_memory = None
        for attempt in range(3):
            try:
                updated_memory = model.invoke(
                    [formatted_system_message, user_prompt],
                    {"disable_streaming": True},
                )
                break
            except Exception:
                if attempt < 2:
                    time.sleep(1)
        if updated_memory is not None:
            try:
                store.put(namespace, "user_memory", {"preference": updated_memory.model_dump()})
            except Exception as e:
                print(f"[memory] 用户画像写入失败（已忽略）: {e}")

    if not rounds:
        return None

    recent_rounds = rounds[-RECENT_ROUNDS:]
    older_rounds = rounds[:-RECENT_ROUNDS]

    keep_ids = {mid for round_ in recent_rounds for mid in round_["ids"]}
    remove = [
        RemoveMessage(id=m.id)
        for m in messages
        if m.id and m.id not in keep_ids
    ]

    older_text = _rounds_text(older_rounds)
    file_notes = _file_notes(state)
    new_summary = _merge_summary(state.get("summary") or "", older_text, file_notes)

    updates = {}
    if remove:
        updates["messages"] = remove
    if new_summary != (state.get("summary") or ""):
        updates["summary"] = new_summary
    return updates or None
