"""法律咨询 — RAG + LLM 问答

接收用户法律问题，通过 RAG 检索相关法条，基于法律依据进行回答。
"""

from langchain_core.messages import SystemMessage, HumanMessage
from utils.models import create_deepseek_model

from agents.RAG import retrieve_text


CONSULT_PROMPT = """请基于以下法律依据回答用户问题。只输出回答内容，不要输出任何开场白、结束语、建议或注意事项。

## 相关法律依据
{legal_context}

## 输出要求
1. 严格依据上述法律条文回答，不得编造法条
2. 引用的法条需标注具体名称和条款号
3. 如果检索到的法律依据不足以完整回答问题，如实告知
4. 如果用户问题与法律无关，直接回复"该问题不属于法律咨询范畴"
5. 禁止输出任何解释性文字、开场白或结束语
6. 必须使用中文回答"""


_model = create_deepseek_model(temperature=0.3)


def consult(question: str) -> str:
    """对用户的法律问题进行咨询回答。

    流程：
    1. 通过 RAG 检索 top 10 相关法条
    2. 构建包含法律依据的 prompt
    3. LLM 生成回答
    """
    if not question or not question.strip():
        return "请输入您的法律问题。"

    try:
        laws = retrieve_text(question, top_k=10)
    except Exception as e:
        return f"法律检索失败: {e}"

    if not laws:
        legal_context = "未检索到直接相关的法律条文。"
    else:
        legal_context = "\n\n".join(
            f"[来源: {r['metadata'].get('heading', '法律法规')}]\n"
            f"{r['content']}\n"
            f"相似度: {r['distance']:.4f}" if r.get('distance') else ""
            for r in laws
        )

    response = _model.invoke([
        SystemMessage(content=CONSULT_PROMPT.format(legal_context=legal_context)),
        HumanMessage(content=question),
    ])

    return response.content


class ConsultorAgent:
    """保持与 legal/__init__.py 调用的兼容。"""

    @staticmethod
    def consult(question: str) -> str:
        return consult(question)
