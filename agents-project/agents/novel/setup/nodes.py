"""开书 agent 的节点：greeting（暖场）、discuss（生成问题）、ask_user（中断等回答）、
maintain（提取+路由）、confirm（过目）、save（落库）。

控制流：greeting → maintain → discuss → ask_user → maintain（循环）
    ↘ all_done ↗                  ↕ resume
                        ask_user → maintain
confirm → 退回 → maintain
"""
import logging
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from ..utils.model import BackupMainModel, MainModel
from agents.utils.models import ainvoke_with_fallback, parse_json_value
from ..utils.novel_information import save_novel_meta
from ..utils.verdict import verdict
from .prompt import CONFIRM_PROMPT, DISCUSS_SYSTEM, MAINTAIN_SYSTEM
from .settings import (
    DEPENDENCIES,
    FIELD_PROMPTS,
    SETTING_FIELDS,
    SETTING_LABELS,
    missing_fields,
    render_settings,
    wrap_setting,
)
from .state import SetupState

logger = logging.getLogger(__name__)

# ── with_structured_output 的 schema ──────────────────────────


class ProtagonistSetting(BaseModel):
    """主角设定：LLM 直接按这个 schema 输出结构体，不再靠 regex 从字符串里抠。"""
    name: str = Field(description="主角姓名")
    description: str = Field(
        description="性别、身份、性格、金手指或核心能力、反差点等详细设定",
    )


class WorldRuleSetting(BaseModel):
    """世界规则设定：LLM 直接按 schema 输出 name + rule，不再靠 split 猜边界。"""
    name: str = Field(description="规则名称/标题")
    rule: str = Field(description="规则详细内容")


class MaintainOutput(BaseModel):
    """maintain 节点从对话中提取的结构化设定。"""
    settings_updates: dict[str, str | ProtagonistSetting | WorldRuleSetting] = Field(
        default_factory=dict,
        description="本轮用户明确确认的设定，key=字段名，value=确认的内容。只包含有变化的字段。",
    )
    clear_fields: list[str] = Field(
        default_factory=list,
        description="用户要求重议的字段名列表（从 confirm 退回场景）。",
    )
    user_choice: str = Field(
        default="",
        description="解析用户本轮的真实意图摘要",
    )
    next_question: str = Field(
        default="",
        description="discuss 下一轮要问的字段名，全部收齐则写空串",
    )
    next_hint: str = Field(
        default="",
        description="给 discuss 的下一轮提问建议",
    )

# discuss 节点要用模型说话，所以**不能** disable_streaming。
try:
    _discussModel = MainModel(temperature=0.6)
    _discussModel_backup = BackupMainModel(temperature=0.6)
except Exception:
    _discussModel = None
    _discussModel_backup = None

# maintain 节点需要理解对话、提取结构化数据，使用低温模型保证稳定性。
try:
    _maintainModel = MainModel(temperature=0.0)
    _maintainModel_backup = BackupMainModel(temperature=0.0)
except Exception:
    _maintainModel = None
    _maintainModel_backup = None


# ============================================================
# 辅助函数
# ============================================================

def _build_discuss_system(settings: dict, next_question: str, next_hint: str, user_choice: str = "", last_question: str = "") -> str:
    """为 discuss 节点构造系统提示词。"""
    missing = missing_fields(settings)

    if settings:
        settings_text = render_settings(settings)
    else:
        settings_text = "（还没有已确定的设定）"

    if missing:
        missing_text = "\n".join(f"- {SETTING_LABELS.get(f, f)}" for f in missing)
    else:
        missing_text = "（全部已定）"

    # 确定当前要问的字段
    field = next_question or "novel_tropes"
    field_label = SETTING_LABELS.get(field, field)
    field_prompt = FIELD_PROMPTS.get(field, FIELD_PROMPTS["novel_tropes"])

    # 全部已定但 next_question 为空 → 用户想改设定，用通用修改提示
    if not next_question and not missing:
        field_label = "（用户想修改设定）"
        field_prompt = "用户对已确定的设定有修改意见。请根据他刚才说的话，问他具体想改哪一项。一次只问一项。"

    return DISCUSS_SYSTEM.format(
        settings=settings_text,
        missing=missing_text,
        field_label=field_label,
        hint=next_hint or "根据用户前面的回答自然地引出这一项的讨论",
        field_prompt=field_prompt,
        user_choice=user_choice or "（还没有上一轮的选择记录）",
        last_question=last_question or "（还没有上一轮的问题记录）",
    )


def _build_maintain_system(settings: dict) -> str:
    """为 maintain 节点构造系统提示词。"""
    missing = missing_fields(settings)

    if settings:
        settings_text = render_settings(settings)
    else:
        settings_text = "（还没有已确定的设定）"

    if missing:
        missing_text = "\n".join(f"- {SETTING_LABELS.get(f, f)}" for f in missing)
    else:
        missing_text = "（全部已定）"

    return MAINTAIN_SYSTEM.format(
        settings=settings_text,
        missing=missing_text,
    )


def _parse_maintain_json(text: str) -> dict | None:
    """从 maintain LLM 回复中解析 JSON。"""
    # 去掉可能的 ```json 围栏
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        result = parse_json_value(cleaned)
        if isinstance(result, dict):
            return result
    except (ValueError, TypeError):
        pass
    return None


# ============================================================
# greeting — 暖场
# ============================================================

async def greeting(state: SetupState, config: RunnableConfig) -> Command:
    """打招呼节点：只在第一轮运行，给出友好问候后转到 maintain 节点。"""
    welcome = (
        "你好，想开一本什么样的书？随便说，模糊也行 —— "
        "书名、题材、主角、核心冲突这些，我会照着畅销书的套路一项一项问你，"
        "你拿不准就说「你定」。"
    )
    answer = interrupt(welcome)
    return Command(
        goto="maintain",
        update={
            "user_message": "" if answer is None else str(answer),
            "messages": [AIMessage(content=welcome)],
        },
    )


# ============================================================
# discuss — 生成问题
# ============================================================

async def discuss(state: SetupState, config: RunnableConfig) -> Command:
    """对话节点：调 LLM 生成问题后路由到 ask_user。

    discuss 本身不调用 interrupt（interrupt 在 ask_user 里），
    所以 resume 重跑不会触发多余的 LLM 调用。
    """

    # ── 生成问题（从 maintain 的指引来）──
    settings = dict(state.get("settings") or {})
    print(f"[DEBUG discuss] current settings={settings}")
    next_question = (state.get("next_question") or "") or ""
    next_hint = (state.get("next_hint") or "") or ""
    user_choice = state.get("user_choice") or ""
    # user_message 由 maintain 传过来，作为 HumanMessage 让 discuss 能自然接话
    last_reply = (state.get("user_message") or "").strip()
    # 上一条 AI 问题，让"选1"这类简短回复有上下文
    msgs_list = state.get("messages") or []
    last_question = msgs_list[-1].content if msgs_list and last_reply else ""

    system = _build_discuss_system(settings, next_question, next_hint, user_choice, last_question)

    msgs = [SystemMessage(content=system)]
    if last_reply:
        msgs.append(HumanMessage(content=last_reply))

    print(f"[DEBUG discuss] system_prompt 末 200 字={system[-200:]}, user_choice={user_choice}, last_reply={last_reply[:100]}")
    reply = await ainvoke_with_fallback(_discussModel, _discussModel_backup, msgs)
    question = reply.content if isinstance(reply.content, str) else ""
    print(f"[DEBUG discuss] 回答={question[:300]}")

    # 不 interrupt，存问题到 state 后路由到 ask_user
    return Command(
        goto="ask_user",
        update={
            "messages": [AIMessage(content=question)],
            "question": question,
            "next_question": "",
            "next_hint": "",
        },
    )


# ============================================================
# ask_user — 中断等用户答复
# ============================================================

async def ask_user(state: SetupState, config: RunnableConfig) -> Command:
    """只 interrupt，不调 LLM，不做任何判断。

    discuss 把问题生成好存 state.question，ask_user 只管 interrupt 等回答，
    resume 后直接路由到 maintain。
    """
    answer = interrupt(state.get("question") or "")
    return Command(
        goto="maintain",
        update={"user_message": "" if answer is None else str(answer)},
    )


# ============================================================
# maintain — 提取设定 + 路由
# ============================================================

async def maintain(state: SetupState, config: RunnableConfig) -> Command:
    """提取节点：调 LLM 读取最近 AIMessage + user_message，提取设定，处理依赖，路由。

    maintain 的 LLM 调用不存入 messages（一次性分析）。
    """
    user_msg = (state.get("user_message") or "").strip()
    settings = dict(state.get("settings") or {})
    messages = list(state.get("messages") or [])

    system = _build_maintain_system(settings)

    # 读取最近 6 条 AIMessage + 用户本轮回答作为上下文
    ai_messages = [m for m in messages if isinstance(m, AIMessage)][-6:]
    context = list(ai_messages)
    if user_msg:
        context.append(HumanMessage(content=user_msg))

    print(f"[DEBUG maintain] ai_messages前6={[str(m)[:200] for m in ai_messages]}, user_msg={user_msg}")

    updates: dict = {}
    to_clear: list[str] = []
    user_choice = ""
    next_question = ""
    next_hint = ""

    try:
        # 优先用 with_structured_output（工具调用模式，输出直接是结构体）
        structured = _maintainModel.with_structured_output(MaintainOutput)
        result = await ainvoke_with_fallback(structured, _maintainModel_backup.with_structured_output(MaintainOutput), [
            SystemMessage(content=system),
            *context,
        ])
        raw_updates = result.settings_updates or {}
        for field, value in raw_updates.items():
            if field not in SETTING_FIELDS:
                continue
            if isinstance(value, ProtagonistSetting):
                updates[field] = [{"name": value.name, "description": value.description}]
            elif isinstance(value, WorldRuleSetting):
                updates[field] = [{"name": value.name, "rule": value.rule}]
            elif isinstance(value, str) and value.strip():
                updates[field] = wrap_setting(field, value.strip())
        clear_fields = result.clear_fields or []
        if isinstance(clear_fields, list):
            to_clear = [f for f in clear_fields if f in SETTING_FIELDS]
        user_choice = result.user_choice or ""
        next_question = result.next_question or ""
        next_hint = result.next_hint or ""
        print(f"[DEBUG maintain] with_structured_output 成功")
    except Exception as e:
        # with_structured_output 不支持 → 降级为 response_format（JSON mode）
        print(f"[DEBUG maintain] with_structured_output 失败 ({e})，降级为 response_format")
        try:
            reply = await ainvoke_with_fallback(_maintainModel, _maintainModel_backup, [
                SystemMessage(content=system),
                *context,
            ], response_format={"type": "json_object"})
        except Exception:
            logger.warning("maintain response_format 也不受支持，降级为普通调用")
            reply = await ainvoke_with_fallback(_maintainModel, _maintainModel_backup, [
                SystemMessage(content=system),
                *context,
            ])
        raw = reply.content if isinstance(reply.content, str) else ""
        print(f"[DEBUG maintain] LLM回答={raw[:500]}")
        parsed = _parse_maintain_json(raw)

        if parsed:
            raw_updates = parsed.get("settings_updates") or {}
            for field, value in raw_updates.items():
                if field in SETTING_FIELDS and str(value).strip():
                    updates[field] = wrap_setting(field, str(value).strip())
            clear_fields = parsed.get("clear_fields") or []
            if isinstance(clear_fields, list):
                to_clear = [f for f in clear_fields if f in SETTING_FIELDS]
            user_choice = str(parsed.get("user_choice") or "")
            next_question = str(parsed.get("next_question") or "")
            next_hint = str(parsed.get("next_hint") or "")

    # ── 先清除要重议的项及其依赖 ──
    for field in to_clear:
        logger.info("maintain 清空 %s（用户要修改）", field)
        settings.pop(field, None)
        for dep in DEPENDENCIES.get(field, []):
            if dep in settings:
                logger.info("maintain 连带清空依赖项 %s", dep)
                settings.pop(dep, None)

    # ── 合并设定 ──
    if updates:
        # 处理依赖：更新了上层设定 → 清空依赖的下层
        for field in updates:
            for dep in DEPENDENCIES.get(field, []):
                if dep in settings:
                    logger.info("maintain 清空依赖项 %s（%s 已更新）", dep, field)
                    settings.pop(dep, None)
        settings.update(updates)

    # ── 校验完整性 ──
    missing = missing_fields(settings)
    all_done = not missing

    if all_done:
        print(f"[DEBUG maintain] 全部设定已齐，路由到 confirm | settings={settings}, user_choice={user_choice}")
        return Command(
            goto="confirm",
            update={
                "settings": settings,
                "next_question": "",
                "next_hint": "",
                "user_message": "",
            },
        )

    # 如果 maintain 没给出 next_question，选第一个缺失项
    if not next_question and missing:
        next_question = missing[0]
        next_hint = f"用户已确定了部分设定，现在该问 {SETTING_LABELS.get(next_question, next_question)}"

    print(f"[DEBUG maintain] 路由到 discuss | next_question={next_question}, user_choice={user_choice}, updates={updates}, to_clear={to_clear}")
    return Command(
        goto="discuss",
        update={
            "settings": settings,
            "next_question": next_question,
            "next_hint": next_hint,
            "user_choice": user_choice,
            "user_message": user_msg,
        },
    )


# ============================================================
# confirm — 过目 + 认可判据
# ============================================================

async def confirm(state: SetupState, config: RunnableConfig) -> Command:
    """把整份设定摆给用户过目，等他答复。

    认可了去 save；要改就回到 maintain 重议。
    """
    settings = state.get("settings") or {}
    text = (
        f"六项都定了，请你过目：\n\n{render_settings(settings)}\n\n"
        "没问题我就记下来，这本书就算建好了；要改哪一项，直接说改哪里。"
    )
    answer = interrupt(text)

    try:
        from ..utils.model import intentModel, _intentModel_backup
        print(f"[DEBUG confirm] answer={str(answer)[:200]}")
        try:
            reply = await intentModel.ainvoke(
                [SystemMessage(content=CONFIRM_PROMPT), HumanMessage(content=str(answer))]
            )
        except Exception:
            reply = await _intentModel_backup.ainvoke(
                [SystemMessage(content=CONFIRM_PROMPT), HumanMessage(content=str(answer))]
            )
    except Exception:
        reply_text = ""
    else:
        reply_text = reply.content if isinstance(reply.content, str) else ""
        print(f"[DEBUG confirm] intentModel回答={reply_text[:300]}")
    approved, _ = verdict(reply_text, "confirmed")

    if approved:
        return Command(goto="save", update={"approved": True})

    # 没认可：回到 maintain，由 maintain 解析用户意图后路由
    return Command(
        goto="maintain",
        update={
            "approved": False,
            "question": "",
            "user_message": str(answer),
        },
    )


# ============================================================
# save — 落库
# ============================================================

async def save(state: SetupState, config: RunnableConfig) -> dict:
    """设定齐了、用户也认可了才落库。"""
    settings = state.get("settings") or {}
    cfg = config.get("configurable") or {}
    novel_id = str(cfg.get("novel_id") or "")
    if state.get("saved") or not state.get("approved") or missing_fields(settings) or not novel_id:
        return {}

    await save_novel_meta(novel_id, str(cfg.get("user_id") or "0"), settings)
    return {
        "saved": True,
        "edit_note": (
            f"《{settings.get('novel_title') or '未命名'}》建好了，设定都记下了。"
            "回书架点开这本书，说一声就能开写第一章。"
        ),
    }


# ============================================================
# 路由
# ============================================================

def route_start(state: SetupState) -> str:
    """已经建好的这本书不再走一遍。"""
    return "done" if state.get("saved") else "greeting"