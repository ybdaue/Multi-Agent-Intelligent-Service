from agents.utils.models import (
    BackupCompressModel, BackupIntentModel, BackupMainModel,
    CompressModel, IntentModel, MainModel,
)

from ..tools.analyze_document import analyze_document
from ..tools.consultor import consultor
from ..tools.draftor import draft_document_agent

legal_tools = [analyze_document, consultor, draft_document_agent]

# 模型实例在模块加载时创建；若 DB 尚未配置模型或 API key 缺失，设 None 使调用自然
# fallback 到备用或兜底逻辑。
try:
    _base = MainModel(service_type="legal", temperature=0.1, disable_streaming=True)
    model = _base.bind_tools(legal_tools) if _base is not None else None
    Intent_model = IntentModel(service_type="legal", temperature=0.1, disable_streaming=True)
    _summarizer_model = CompressModel(service_type="legal", temperature=0.2)
except Exception:
    model = None
    Intent_model = None
    _summarizer_model = None

# ── 备用模型实例（主模型失败时运行时降级使用）────────────
try:
    _backup_base = BackupMainModel(service_type="legal", temperature=0.1, disable_streaming=True)
    model_backup = _backup_base.bind_tools(legal_tools) if _backup_base is not None else None
    Intent_model_backup = BackupIntentModel(service_type="legal", temperature=0.1, disable_streaming=True)
    _summarizer_model_backup = BackupCompressModel(service_type="legal", temperature=0.2)
except Exception:
    model_backup = None
    Intent_model_backup = None
    _summarizer_model_backup = None