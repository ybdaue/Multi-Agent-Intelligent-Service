"""开书 agent 的节点：greeting（暖场）、discuss（生成问题）、ask_user（中断等回答）、
maintain（提取+路由）、confirm（过目）、save（落库）。

控制流：greeting → maintain → discuss → ask_user → maintain（循环）
    ↘ all_done ↗                  ↕ resume
                        ask_user → maintain
confirm → 退回 → maintain
"""
import json
import logging
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt

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
    SUB_FIELDS,
    missing_fields,
    render_item,
    render_settings,
    wrap_setting,
)
from .state import SetupState

logger = logging.getLogger(__name__)

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

def _find_numbered_options(messages: list) -> list[tuple[str, str]]:
    """最近的 AI 消息里的编号选项 (序号, 选项文本)，按出现顺序。"""
    for msg in reversed([m for m in (messages or []) if isinstance(m, AIMessage)]):
        opts = re.findall(r'(?:^|\n)\s*(\d+)[.、]\s*(.+)', msg.content)
        if opts:
            return opts
    return []


def _has_ambiguous_numbering(options: list[tuple[str, str]]) -> bool:
    """一轮里给了两组选项：编号从头再来（同一个号出现两次）→ 用户回"1"说不清指哪一组。"""
    nums = [n for n, _ in options]
    return len(nums) != len(set(nums))


def _is_numbered_reply(user_msg: str) -> bool:
    """用户这轮是不是在报编号（"1" / "选1" / "第一个"）。"""
    return bool(re.match(r'^选?\s*(?:\d+|第[一二三四五六七八九十]个)', (user_msg or "").strip()))


def _resolve_numbered_choice(user_msg: str, messages: list) -> tuple[str | None, str]:
    """从用户回复中解析编号选项选择。

    只在"上一轮只有一组编号"时用 —— 多组编号已在 maintain 里判为歧义、走不到这里（否则按
    位置取号会把 "1" 一律认成第一组）。用最近的 AI 消息里那组编号判断用户命中了第几项；选了
    之后还带附加意见（"1. 但世界观还要加点..."）一并返回。

    Returns:
        (option_text, extra_text) — option_text 是选中的选项内容，None 表示没匹配到
        extra_text 是选了之后用户额外写的内容
    """
    if not user_msg or not messages:
        return None, ""

    options = _find_numbered_options(messages)
    if not options:
        return None, ""

    user_trimmed = user_msg.strip().replace(' ', ' ')

    # 模式1：纯数字 "1" 或 "选1" / "选 1"
    m = re.match(r'^选?\s*(\d+)\s*$', user_trimmed)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(options):
            return options[idx][1].strip(), ""

    # 模式2："1. 但我觉得..." / "选1，还要..." / "选 1 ，然后..."
    m = re.match(r'^选?\s*(\d+)\s*[.。，,、]\s*(.+)', user_trimmed, re.DOTALL)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(options):
            return options[idx][1].strip(), m.group(2).strip()

    # 模式3："第一个" / "选第二个吧"
    m = re.match(r'^选?第([一二三四五六七八九十\d])个\s*[，,。]?\s*(.*)', user_trimmed, re.DOTALL)
    if m:
        cn_nums = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}
        idx_str = m.group(1)
        idx = (cn_nums.get(idx_str, 0) - 1) if idx_str in cn_nums else (int(idx_str) - 1 if idx_str.isdigit() else -1)
        if 0 <= idx < len(options):
            return options[idx][1].strip(), m.group(2).strip()

    return None, ""


def _build_discuss_system(settings: dict, field: str, next_hint: str, user_choice: str = "") -> str:
    """为 discuss 节点构造系统提示词。

    field 是**已经定好**的当前要问字段 —— 由 discuss 选：maintain 指了就听它的，没指就取第一个
    缺失项。空串表示六项都定了、用户在提修改意见。
    """
    missing = missing_fields(settings)

    if settings:
        settings_text = render_settings(settings)
    else:
        settings_text = "（还没有已确定的设定）"

    if missing:
        missing_text = "\n".join(f"- {SETTING_LABELS.get(f, f)}" for f in missing)
    else:
        missing_text = "（全部已定）"

    if field:
        field_label = SETTING_LABELS.get(field, field)
        field_prompt = FIELD_PROMPTS.get(field, FIELD_PROMPTS["novel_tropes"])
        hint = next_hint or "根据用户前面的回答自然地引出这一项的讨论"
    else:
        # 全部已定但用户还想改：用通用修改提示，让 discuss 问他具体要改哪一项
        field_label = "（用户想修改设定）"
        field_prompt = "用户对已确定的设定有修改意见。请根据他刚才说的话，问他具体想改哪一项。一次只问一项。"
        hint = next_hint or "先接住用户的修改意见，再问他具体想改哪一项"

    return DISCUSS_SYSTEM.format(
        settings=settings_text,
        missing=missing_text,
        field_label=field_label,
        hint=hint,
        field_prompt=field_prompt,
        user_choice=user_choice or "（还没有上一轮的选择记录）",
    )


def _build_maintain_system(settings: dict, asked: str = "") -> str:
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

    asked_text = SETTING_LABELS.get(asked, asked) if asked else "（不清楚，可能是用户在提修改意见）"

    return MAINTAIN_SYSTEM.format(
        settings=settings_text,
        missing=missing_text,
        asked=asked_text,
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


def _store_value(field: str, value) -> object | None:
    """把 maintain 提取到的原始值转成 settings 里的存法，转不出有效值返回 None。

    LLM 侧对主角用语义键（gender/power/contrast），这里映射到 novel_character 的库列名
    （sex/ability/description），与 render_protagonists、落库端同一口径。
    """
    if field == "novel_protagonists":
        if isinstance(value, str):
            return wrap_setting(field, value.strip()) if value.strip() else None
        items = value if isinstance(value, list) else [value]
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            entry = {
                "name": it.get("name") or "",
                "sex": it.get("sex") or it.get("gender") or "",
                "identity": it.get("identity") or "",
                "personality": it.get("personality") or "",
                "ability": it.get("ability") or it.get("power") or "",
                "description": it.get("description") or it.get("contrast") or "",
            }
            if entry["name"]:
                out.append(entry)
        return out or None

    if field in SUB_FIELDS:
        if isinstance(value, dict):
            sub_defs = SUB_FIELDS[field]
            kept = {k: value[k] for k in sub_defs if value.get(k)}
            return kept or None
        if isinstance(value, str):
            return wrap_setting(field, value.strip()) if value.strip() else None
        return None

    if field == "novel_world_rules":
        if isinstance(value, str):
            return wrap_setting(field, value.strip()) if value.strip() else None
        items = value if isinstance(value, list) else [value]
        out = [
            {"name": it.get("name") or "", "rule": it.get("rule") or ""}
            for it in items if isinstance(it, dict)
        ]
        return out or None

    if isinstance(value, (dict, list)):
        return wrap_setting(field, json.dumps(value, ensure_ascii=False))

    text = str(value).strip()
    return wrap_setting(field, text) if text else None


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

    discuss 不做任何"哪一项定了"的判断 —— 那是 maintain 的事。它只负责：就 maintain 指定的
    那一项，接住用户上一轮的话，把问题问出去。用户的回答已由 maintain 解析成 user_choice，
    discuss 不再自己回头翻上一轮的问题去重解编号（那样会和 maintain 各解各的）。

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

    # 这一轮问哪一项：maintain 指了听它的，没指就取第一个缺失项；六项都齐了给空（用户在提修改）
    missing = missing_fields(settings)
    if next_question:
        field = next_question
    elif missing:
        field = missing[0]
    else:
        field = ""

    system = _build_discuss_system(settings, field, next_hint, user_choice)

    msgs = [SystemMessage(content=system)]
    if last_reply:
        # 用户原话照旧带上，discuss 靠它"接得住"；但"1 指哪个选项"已由 user_choice 定了，
        # 这里不再把上一轮的问题喂进来，免得它又自己解一遍编号。
        msgs.append(HumanMessage(content=last_reply))

    print(f"[DEBUG discuss] field={field}, user_choice={user_choice}, last_reply={last_reply[:100]}")
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
            "asked_field": field,
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
    asked = state.get("asked_field") or ""

    # ── 编号歧义兜底：上一轮要是给了两组编号（同一个号出现两次），用户回"1"指哪组说不清 ——
    #    不按位置硬解、也不让模型去猜，直接把话题拉回上一轮问的那一项重问一遍（下一轮只给一组）。 ──
    options = _find_numbered_options(messages)
    if options and _has_ambiguous_numbering(options) and _is_numbered_reply(user_msg):
        still_missing = missing_fields(settings)
        target = asked or (still_missing[0] if still_missing else "")
        target_label = SETTING_LABELS.get(target, target) or "这一项"
        logger.warning("maintain 检测到上一轮有多组编号，用户 %r 指哪组说不清，判为歧义", user_msg[:20])
        return Command(
            goto="discuss",
            update={
                "settings": settings,
                "next_question": target,
                "next_hint": (
                    f"上一轮一口气给了两组编号选项，用户回的编号说不清指哪一组。"
                    f"这一轮只就「{target_label}」重新问，且只给一组编号选项。"
                ),
                "user_choice": "用户回了编号，但上一轮给了多组选项，指哪组说不清，需要重新单独问这一项。",
                "user_message": user_msg,
            },
        )

    system = _build_maintain_system(settings, asked)

    # 读取最近 6 条 AIMessage + 用户本轮回答作为上下文
    ai_messages = [m for m in messages if isinstance(m, AIMessage)][-6:]
    context = list(ai_messages)
    if user_msg:
        context.append(HumanMessage(content=user_msg))

    print(f"[DEBUG maintain] ai_messages前6={[str(m)[:200] for m in ai_messages]}, user_msg={user_msg}")

    # ── 预解析编号选项：用户说"选1"/"1"/"第一个"时直接注入选项内容 ──
    resolved_choice, extra_input = _resolve_numbered_choice(user_msg, messages)
    if resolved_choice:
        injection = f"[系统解析：用户选择了编号选项，对应内容为「{resolved_choice}」]"
        if extra_input:
            injection += f"\n[用户附加意见：{extra_input}]"
        context.append(SystemMessage(content=injection))
        logger.info("maintain 预解析到编号选择：%s | 附加意见：%s", resolved_choice[:60], extra_input or "无")

    updates: dict = {}
    to_clear: list[str] = []
    user_choice = ""
    next_question = ""
    next_hint = ""

    # 结构化输出走 DeepSeek 的 JSON Output：response_format={"type": "json_object"}。
    # **不用 with_structured_output** —— 它发的是 response_format=json_schema，DeepSeek 一律回
    # 400 "This response_format type is unavailable now"，每轮白搭两次调用。JSON Output 有两个
    # 硬性要求，MAINTAIN_SYSTEM 都已满足：prompt 里含 "json" 字样 + 给出输出示例。
    try:
        reply = await ainvoke_with_fallback(_maintainModel, _maintainModel_backup, [
            SystemMessage(content=system),
            *context,
        ], response_format={"type": "json_object"})
    except Exception:
        # JSON mode 也不可用（换个厂商/模型时可能如此）→ 普通调用，靠提示词约束 + 自行解析。
        logger.warning("maintain JSON mode 不可用，降级为普通调用")
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
            if field not in SETTING_FIELDS:
                continue
            stored = _store_value(field, value)
            if stored:
                updates[field] = stored
        clear_fields = parsed.get("clear_fields") or []
        if isinstance(clear_fields, list):
            to_clear = [f for f in clear_fields if f in SETTING_FIELDS]
        user_choice = str(parsed.get("user_choice") or "")
        next_question = str(parsed.get("next_question") or "")
        next_hint = str(parsed.get("next_hint") or "")

    # ── panel edit：用户通过右侧面板改了某一项 ──
    # 面板交上来的就是"这一项的完整新内容"（结构化项是 JSON），直接按标记格式确定性落定，
    # 不指望 LLM 转述得准 —— 它漏一处子要素，这一项就会被判成没收齐、白问一轮。
    _EDIT_PATTERN = re.compile(
        r'用户修改了设定项「([^」]+)」为：\n【设定项】[^】]*\n【内容】(.+?)\n【设定结束】',
        re.S,
    )
    edited_field = ""
    edited_content = ""
    edit_match = _EDIT_PATTERN.search(user_msg)
    if edit_match:
        candidate = edit_match.group(1).strip()
        if candidate in SETTING_FIELDS:
            edited_field = candidate
            edited_content = edit_match.group(2).strip()
            logger.info("maintain 检测到 panel edit：%s → %s", edited_field, edited_content[:60])
            # 结构化项面板交上来的是 JSON，先解成对象再走 _store_value（主角映射库列名、
            # 套路/风格留子字段 key）；非结构化项是散文，解不出就当字符串原样收。
            try:
                parsed_content = json.loads(edited_content)
            except (json.JSONDecodeError, TypeError, ValueError):
                parsed_content = edited_content
            value = _store_value(edited_field, parsed_content)
            if value:
                updates[edited_field] = value
            # 用自然语言替换原始标记文本，让 discuss 能接住这句话
            label = SETTING_LABELS.get(edited_field, edited_field)
            user_msg = f"我修改了{label}：{edited_content}"

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

    # LLM 给出的 next_question 可能指向已收集字段（LLM 不知道代码层清空的依赖项），
    # 如果它有缺失项可问但指向了已收集的字段，纠正到第一个缺失项上。
    if next_question and next_question not in missing:
        next_question = missing[0]
        next_hint = f"用户已确定了部分设定，现在该问 {SETTING_LABELS.get(next_question, next_question)}"

    # 如果 maintain 没给出 next_question，选第一个缺失项
    if not next_question and missing:
        next_question = missing[0]
        next_hint = f"用户已确定了部分设定，现在该问 {SETTING_LABELS.get(next_question, next_question)}"

    # panel edit 改的那一项若仍没收齐，就把话题拉回它，让 discuss 回聊补全；已经齐了
    # 就照上面的缺失项接着问（面板里改齐一项不该把话题拽回去）。
    if edited_field and edited_field in missing:
        next_question = edited_field
        next_hint = f"用户通过面板修改了此项（{edited_content[:40]}），内容可能不完整，需要和他讨论确认补充"

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

    # tropes/style 在 settings 里是 dict（子字段结构化），但库里是 TEXT 列、前端（详情页 /
    # 后台）也按整串展示和编辑 —— 落库前排成人话一行，与旧数据同形状。writer/reader 读的
    # 也是这串，JSON 摆进提示词没法看。
    db_settings = dict(settings)
    for field in ("novel_tropes", "novel_style"):
        value = db_settings.get(field)
        if value and not isinstance(value, str):
            db_settings[field] = render_item(field, value).replace("\n", "；")

    await save_novel_meta(novel_id, str(cfg.get("user_id") or "0"), db_settings)
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