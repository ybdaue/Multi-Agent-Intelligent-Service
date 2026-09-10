"""法律咨询 — create_agent + retrieve_law 问答

接收用户法律问题，由 agent 调用 retrieve_law 工具检索相关法条，再基于返回的法律依据作答。
"""

from langchain.agents import create_agent
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import tool

from agents.utils.models import MainModel

from ..tools.retrieve_law import retrieve_law_basis


CONSULT_PROMPT = """你是一位法律咨询助手。回答用户前，先用 retrieve_law_basis 工具检索与问题相关的法条原文（query 填用户完整问题），并严格依据工具返回的法律依据作答。

只输出回答内容，不要输出任何开场白、结束语、建议或注意事项。

## 回答要求
1. 若判断用户问题与法律无关（问候、闲聊、非法律事务等），直接回复"该问题不属于法律咨询范畴"，无需检索
2. 严格依据 retrieve_law_basis 返回的法条回答，不得编造法条
3. 引用的法条需标注具体名称和条款号
4. 若工具未检索到足够依据，如实告知，并建议咨询执业律师
5. 禁止输出任何解释性文字、开场白或结束语
6. 必须使用中文回答"""


def _last_agent_text(result: dict) -> str:
    """从 create_agent 结果里取最终无工具调用的 AI 文本。"""
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            content = msg.content
            if content:
                return content if isinstance(content, str) else str(content)
    return "" if not messages else str(messages[-1].content)


_consult_agent = create_agent(
    model=MainModel(temperature=0.3),
    tools=[retrieve_law_basis],
)


def consult(question: str) -> str:
    """对用户的法律问题进行咨询回答。

    流程：
    1. 模型判断问题是否属于法律咨询；是则调用 retrieve_law 工具检索法条
    2. 基于工具返回的法律依据生成回答
    """
    if not question or not question.strip():
        return "请输入您的法律问题。"

    result = _consult_agent.invoke(
        {
            "messages": [
                SystemMessage(content=CONSULT_PROMPT),
                HumanMessage(content=question),
            ]
        },
        config={"recursion_limit": 12},
    )
    return _last_agent_text(result)


class ConsultorAgent:
    """保持与 legal/__init__.py 调用的兼容。"""

    @staticmethod
    def consult(question: str) -> str:
        return consult(question)


@tool
def consultor(question: str) -> str:
    """解释法律概念、回答法律咨询问题。

    基于法律法规知识库检索相关法条，给出专业、准确的法律解答。

    Args:
        question: 用户的法律问题或需要解释的法律概念
    """
    print("咨询工具被调用了")
    return consult(question)
