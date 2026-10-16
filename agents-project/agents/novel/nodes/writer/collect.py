"""collect 节点（查库，不调模型）：切正文与台账、定标题字数、算序号，收入 active_chapter。"""
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END
from langgraph.types import Command

from ...utils.chapter_information import (
    count_chapter_words,
    next_chapter_order,
    split_title,
)
from ...utils.ledger import (
    ENTITY_SCAN_TYPES,
    NEW_ENTITY_SPEC,
    auto_complete_refs,
    fetch_names,
    fetch_ref_names,
    normalize_new,
    parse_ledger,
    split_submission,
)
from ..utils.reply import last_reply
from .helpers import _card_lines
from .state import WriterState


def _name_index(known_rows) -> dict[str, list[tuple[str, str]]]:
    """目录行 → {refType: [(名字, id)]}，供 planner settings 的 name→id 解析。"""
    index: dict[str, list[tuple[str, str]]] = {}
    for ref_type, ref_id, name in known_rows:
        text = str(name or "").strip()
        if text:
            index.setdefault(ref_type, []).append((text, ref_id))
    return index


def _resolve_name(index: dict, ref_type: str, name: str) -> str | None:
    """名字 → 目录里的 id：精确匹配优先，退化为子串（"青锋" 对 "青锋剑"）。都没有就给 None。"""
    rows = index.get(ref_type) or []
    partial = None
    for text, ref_id in rows:
        if text == name:
            return ref_id
        if partial is None and (name in text or text in name):
            partial = ref_id
    return partial


def _merge_settings(refs: list[dict], settings, known_rows) -> list[dict]:
    """planner 的任务卡 settings 候选并进 refs（§5.4）：名字解析成 id 后补一条 mention。

    planner 是候选、writer 才是准 —— role 取最轻的 mention，同一条已由 writer 报过（含更重的
    role）就跳过。解析不出 id 的（名字对不上目录）丢弃，并报一行计数别静默吞。
    """
    index = _name_index(known_rows)
    seen = {(r["refType"], r["refId"]) for r in refs}
    dropped = 0
    for item in settings if isinstance(settings, list) else []:
        if not isinstance(item, dict):
            continue
        ref_type = str(item.get("refType") or "").strip()
        name = str(item.get("name") or "").strip()
        if ref_type not in ENTITY_SCAN_TYPES or not name:
            continue
        target = _resolve_name(index, ref_type, name)
        if target is None:
            dropped += 1
            continue
        if (ref_type, target) in seen:
            continue
        refs.append({"refType": ref_type, "refId": target, "role": "mention"})
        seen.add((ref_type, target))
    if dropped:
        print(f"[writer.collect] planner settings 有 {dropped} 条名字对不上目录，已丢弃", flush=True)
    return refs


def _new_identity(spec: dict, fields: dict):
    """new 一条的"身份"：认身份那一列可以是一列名字，也可以是几列组成的元组（关系是
    两端角色名 + 关系类型三列一起才算一条，见 NEW_ENTITY_SPEC）。"""
    keys = spec["key"]
    if isinstance(keys, tuple):
        return tuple(fields.get(column, "") for column in keys)
    return fields.get(keys, "")


def _merge_new(writer_new: list[dict], card_new) -> list[dict]:
    """new 以 writer 为准（§5.4）：planner 提了 writer 没写的整条丢弃；同身份（refType + 身份列）
    的条目，只把 writer 空着的字段拿 planner 那份补上（planner 是预台账，兜全字段用）。

    两份都先过 normalize_new：字段白名单、默认值、身份列非空，口径一致才配得上。
    """
    planner = {}
    for entry in normalize_new(card_new):
        spec = NEW_ENTITY_SPEC[entry["refType"]]
        planner[(entry["refType"], _new_identity(spec, entry["fields"]))] = entry["fields"]

    merged: list[dict] = []
    for entry in writer_new:
        spec = NEW_ENTITY_SPEC[entry["refType"]]
        fields = dict(entry["fields"])
        filler = planner.get((entry["refType"], _new_identity(spec, fields)))
        if filler:
            for column, value in filler.items():
                if not fields.get(column) and value:
                    fields[column] = value
        merged.append({"refType": entry["refType"], "fields": fields})
    return merged


async def collect(state: WriterState, config: RunnableConfig) -> Command:
    """收稿：切正文与台账、定标题字数、算序号，阶段线/支线照 planner 的任务卡落。

    字数合格与否**不在这里回炉**：交回父图后由 reader 那一路去判（它在审稿时一并数字数），
    真正的回炉由用户在 confirm_chapter 那儿拍板。这儿只管把这一稿收成 active_chapter。
    """
    content = last_reply(state.get("messages"))
    novel_id = (config.get("configurable") or {}).get("novel_id")
    if not content or not novel_id:
        # 写手什么都没交（或拿不到书号）：这一轮到此为止，不硬造一份空章节。
        return Command(goto=END)

    # 先切台账再数字数：台账是元信息不是正文，混在一起会算进字数、也会被存进正文。
    # 标题行也在这儿摘走（存 chapter_title），正文里不留它 —— 数的是正文，摘不摘都一样。
    prose, ledger_text = split_submission(content)
    prose, title = split_title(prose)
    words = count_chapter_words(prose)

    # 台账两项：用到 / 提示的已有设定、新造的实体。lines 由 planner 的任务卡定，写手不再报。
    # 父链（阶段线挂主线、支线挂阶段线）要照本章的 writer_context 解，所以把上下文一并传进去。
    refs, new_entries, changed_entries, _, resolved = parse_ledger(ledger_text)
    gave_ledger = refs is not None
    known_rows = await fetch_names(novel_id)
    card = state.get("task_card") or {}

    # 预台账合并（§5.4）：refs 以 writer 为准、planner 的 settings 候选补 mention（名字→id 由目录
    # 解析）；new 以 writer 为准、planner 的 card.new 只补 writer 空着的字段。refs=None（这一稿没交
    # 台账）时一律不合并 —— 不拿预台账去冲旧关联。
    new_entries = _merge_new(new_entries, card.get("new"))
    if gave_ledger:
        refs = _merge_settings(refs, card.get("settings"), known_rows)

    # 扫名补漏：本章已绑的同名设定（可能绑的是旧版）优先，不再补出第二版。
    covered = await fetch_ref_names(novel_id, refs)
    refs = auto_complete_refs(refs, prose, known_rows, covered)

    # 本章用的灵感：writer 报了就以它为准（可增可减）；没交台账（refs=None）就退回预台账兜底，
    # 别一条都不剩。必用的（usage=must，典型是风格）无论哪一路都照记 —— 那是系统指定的。
    pre = state.get("chapter_inspirations") or []
    if gave_ledger:
        pre = [i for i in pre if str(i.get("usage") or "") == "must"]
    seen = {r["refId"] for r in refs if r["refType"] == "inspiration"}
    for item in pre:
        iid = item.get("id")
        if iid and iid not in seen:
            refs.append({"refType": "inspiration", "refId": iid, "role": "key"})
            seen.add(iid)

    lines = _card_lines(card, state.get("writer_context") or {})

    # 大纲 ref 由代码从 card 的那几条线派生（与 lines 同源），不由 writer 报 —— 线的关联本该
    # 由「这一段属于哪条线」定，不是模型凭印象标。只 phase / branch（主线不挂）。
    outline_refs = [
        {"refType": "outline", "refId": line["id"], "role": "key"}
        for line in lines
        if line.get("id")
    ]

    # 序号以库里的为准（最大序号 + 1），不接受调用方指定。
    chapter_order = await next_chapter_order(novel_id)
    return Command(
        goto=END,
        update={
            "active_chapter": {
                "chapter_id": "",
                "chapter_title": title or "未命名",
                "chapter_order": chapter_order,
                "chapter_status": "draft",
                "chapter_word_count": words,
                "chapter_summary": "",
                "chapter_content": prose,
                "past_summary": {},
                "chapter_state": {},
                "chapter_inspirations": [],
                "chapter_refs": refs,
                "chapter_new": new_entries,
                "chapter_changed": changed_entries,
                # 本章收尾掉的伏笔 id：落库时置它们为已收尾（见 ledger.write_ledger）。
                "chapter_resolved": resolved,
                "chapter_lines": lines,
                "chapter_outline_refs": outline_refs,
            },
            # 写新章不改已有内容、无严重程度可言：显式清空，免得上一轮改稿的 grade 残留下来，
            # 让这一章被 route_after_draft 误判成 L1/L2 而少审。
            "change_grade": "",
        },
    )