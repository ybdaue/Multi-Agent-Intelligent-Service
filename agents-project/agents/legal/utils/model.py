from agents.utils.models import CompressModel, IntentModel, MainModel

from ..tools.analyze_document import analyze_document
from ..tools.consultor import consultor
from ..tools.draftor import draft_document_agent

legal_tools = [analyze_document, consultor, draft_document_agent]

# disable_streaming 必须设在模型实例上：图内带 messages 流式回调时，langchain 的
# invoke 会检测到处理器而自动改走流式通道，把内部输出（意图 JSON、调度寒暄、
# 子 agent 的中间推理）当 token 下发到前端。作为 config 传 {"disable_streaming": True}
# 无效——该开关只在模型属性或 call kwargs 里生效。
model = MainModel(temperature=0.1, disable_streaming=True).bind_tools(legal_tools)
Intent_model = IntentModel(temperature=0.1, disable_streaming=True)
# 收尾总结用：这一路是唯一需要真流式的模型，故不设 disable_streaming。
_summarizer_model = CompressModel(temperature=0.2)
