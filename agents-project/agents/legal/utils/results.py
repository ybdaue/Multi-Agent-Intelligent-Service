import json

from langchain_core.messages import ToolMessage

from ..state import State

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
            content = last_msg.content
            payload = json.loads(content) if isinstance(content, str) else content
            if isinstance(payload, dict) and payload.get("file_id"):
                file_id = payload["file_id"]
                updates["output_file"] = {
                    "type": "db",
                    "suffix": ".docx",
                    "content": file_id,
                    "file_id": file_id,
                    "filename": payload.get("filename", ""),
                }

    except (json.JSONDecodeError, TypeError, AttributeError):
        pass

    return updates


def render_results_text(state: State) -> str:
    """把本轮任务产物整理成可读文本，供 summary 节点生成最终答复。

    analysis_result/answer_result/output_file 会跨轮残留在 state 里，只按本轮
    completed_tasks 取对应产物，避免闲聊轮次把上一轮的文书/分析结论再总结一遍。
    """
    parts = []
    completed = set(state.get("completed_tasks") or [])

    analysis = state.get("analysis_result") if "analyze_file" in completed else None
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

    answer = state.get("answer_result") if "explain_concept" in completed else None
    if answer:
        parts.append(f"【法律咨询答复】\n{answer}")

    of = state.get("output_file") if "draft_document" in completed else None
    if isinstance(of, dict) and of.get("file_id"):
        fname = of.get("filename") or "已生成文书"
        parts.append(f"【已生成文书】{fname}（请点击下载）")

    return "\n\n".join(parts)
