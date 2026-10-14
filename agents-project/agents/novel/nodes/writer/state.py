"""writer 子图的输入 / 输出与内部 state 类型。"""
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from ...state import ChapterMeta, ChapterReview, NovelMeta, merge_chapter


class WriterInput(TypedDict):
    novel: NovelMeta
    active_chapter: ChapterMeta
    chapter_review: ChapterReview
    chapter_attempt: int
    edit_feedback: str
    user_message: str
    inspirations: list                  # 本轮用户在对话框挑中的库内灵感（带 id）
    chapter_inspirations: list          # 上一轮残留的本章灵感，prepare 会清掉重定
    writer_context: dict                # resolve 预查的上下文，prepare 复用跳过查库


class WriterOutput(TypedDict):
    """交回父图的：这一章，和回炉计数。子图自己的对话与内部计数不上交。"""

    active_chapter: ChapterMeta
    chapter_review: ChapterReview
    chapter_attempt: int
    chapter_inspirations: list          # planner 定的本章灵感，交回父图给 reader / update


class WriterState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    novel: NovelMeta
    active_chapter: Annotated[ChapterMeta, merge_chapter]
    chapter_review: ChapterReview
    chapter_attempt: int
    edit_feedback: str
    user_message: str
    inspirations: list                  # 本轮用户在对话框挑中的库内灵感（带 id）
    chapter_inspirations: list          # planner 定的本章最终选用灵感
    writer_context: dict                # resolve 预查的上下文，prepare 复用
    bundle: dict                        # prepare 备好的材料，planner / write 各取所需
    task_card: dict                     # planner 出的任务卡，拼进写手的开场白