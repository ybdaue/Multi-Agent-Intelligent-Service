from agents.utils.models import (
    BackupChatModel, BackupCompressModel, BackupIntentModel, BackupMainModel,
    MainModel, IntentModel, CompressModel,
)

try:
    mainModel = MainModel(service_type="novel",temperature=0.1, disable_streaming=True)
    intentModel = IntentModel(service_type="novel",temperature=0.1, disable_streaming=True)
    compressModel = CompressModel(service_type="novel",temperature=0.1, disable_streaming=True)
    # 闲聊：输出即最终答复，不绑工具，保留流式 —— 图里唯一直接交付前端的一路。
    chatModel = MainModel(service_type="novel",temperature=0.7)
except Exception:
    mainModel = None
    intentModel = None
    compressModel = None
    chatModel = None

# ── 备用模型实例（主模型失败时运行时降级使用）────────────
try:
    _mainModel_backup = BackupMainModel(service_type="novel", temperature=0.1, disable_streaming=True)
    _intentModel_backup = BackupIntentModel(service_type="novel", temperature=0.1, disable_streaming=True)
    _compressModel_backup = BackupCompressModel(service_type="novel", temperature=0.1, disable_streaming=True)
    _chatModel_backup = BackupChatModel(service_type="novel", temperature=0.7)
except Exception:
    _mainModel_backup = None
    _intentModel_backup = None
    _compressModel_backup = None
    _chatModel_backup = None