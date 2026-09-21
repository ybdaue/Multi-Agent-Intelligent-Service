from typing import List, Literal, Optional, TypedDict, Union

from langgraph.graph import MessagesState
from pydantic import Field


class FileSource(TypedDict):
    type: Literal["bytes", "path", "db"]
    suffix: str
    content: Union[str, bytes]
    file_id: str


class State(MessagesState):
    # ===== 用户输入 =====
    userId: int = 0
    user_message: str
    file_source: Optional[FileSource]
    doc_ids: List[str] = Field(default_factory=list)

    # ===== 偏好 =====
    preference: List[str] = Field(default_factory=list)

    # ===== 对话记忆 =====
    summary: str = Field(default="")

    # ===== 流程控制 =====
    step: int = Field(default=0)
    max_step: int = Field(default=10)

    # ===== 任务栈 =====
    primary_intent: Optional[Literal["draft", "analyze", "consult"]] = None
    pending_tasks: List[str] = Field(default_factory=list)
    completed_tasks: List[str] = Field(default_factory=list)
    task_context: dict = Field(default_factory=dict)

    # ===== 产物 =====
    analysis_result: Optional[dict] = None  # 文件分析结果
    answer_result: Optional[str]            # 法律咨询结果
    output_file: Optional[FileSource]       # 输出文件
