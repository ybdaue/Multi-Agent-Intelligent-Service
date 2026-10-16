"""reader 子图的输入 / 输出与内部 state 类型。"""
from typing import Annotated, List, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from ...state import ChapterConflict, ChapterMeta, ChapterReview, NovelMeta


class ReaderInput(TypedDict):
    novel: NovelMeta
    active_chapter: ChapterMeta
    user_message: str
    inspirations: list                  # 用户这一轮给的素材，R-Style 拿它判贴不贴
    chapter_inspirations: list          # 本章最终选用的灵感，style 拿它逐条核写作指引有没有落地
    writer_context: dict                # resolve 预查的上下文，gather 复用跳过查库
    # 重写回炉时由上一趟带过来的影响台账：里面 reader 自己写的问题行要在这里翻成已修复。
    change_impact: List[dict]
    # 这一稿的严重程度（L1/L2/L3，空 = 没分级）。gather 之后据它派发审查员：
    # L2 只跑 logic+pacing，其余（L3 / 空）跑全量。L1 在父图就被 route_after_draft 拦下了，进不来。
    change_grade: str


class ReaderOutput(TypedDict):
    """交回父图的：这一稿的审查结论，用户要求跟库里对不上的那几处，和审查问题的影响行。"""

    chapter_review: ChapterReview
    chapter_conflicts: List[ChapterConflict]
    change_impact: List[dict]           # 问题行（pending）或重写审过后的翻正行（fixed）


class _Chat(TypedDict, total=False):
    """带工具的审查 agent（pacing）的对话。只用来装它自己的消息，材料与结论都在外面。"""

    messages: Annotated[list[AnyMessage], add_messages]


class ReaderState(TypedDict, total=False):
    novel: NovelMeta
    active_chapter: ChapterMeta
    user_message: str
    inspirations: list
    chapter_inspirations: list    # 本章最终选用的灵感（style 核写作指引用）
    writer_context: dict          # resolve 预查的上下文，gather 复用跳过查库
    change_impact: List[dict]     # 重写回炉时由上一趟带过来的影响行
    change_grade: str             # 这一稿的严重程度（L1/L2/L3，空 = 没分级）
    facts: str                    # 本章台账 refs 指向的那些行现在的档案，给 pacing
    logic_input: str              # gather 备好的三份开场白
    pacing_input: str
    style_input: str
    logic_report: str             # 三个审查员各自交上来的原始判词
    pacing_report: str
    style_report: str
    chapter_review: ChapterReview
    chapter_conflicts: List[ChapterConflict]