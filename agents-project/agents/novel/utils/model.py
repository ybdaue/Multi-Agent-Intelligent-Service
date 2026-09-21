from agents.utils.models import MainModel, IntentModel, CompressModel

mainModel = MainModel(temperature=0.1, disable_streaming=True)
intentModel = IntentModel(temperature=0.1, disable_streaming=True)
compressModel = CompressModel(temperature=0.1, disable_streaming=True)
# 闲聊：输出即最终答复，不绑工具，保留流式 —— 图里唯一直接交付前端的一路。
chatModel = MainModel(temperature=0.7)
