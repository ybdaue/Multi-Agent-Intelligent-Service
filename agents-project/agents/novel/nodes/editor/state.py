"""editor 子图的输入 / 输出与内部 state 类型。"""
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from ...state import ChapterMeta, ChapterReview, ChapterTarget, NovelMeta, merge_chapter


class EditorInput(TypedDict):
    """父图传进来的：小说设定、上一轮留在 state 里的章节、reader 的意见、用户的原话、上一轮的影响行。

    change_impact 也投进来：回炉重改是同一处改动，上一轮算好的影响行要接着用（见 _carried_impact）。
    target_chapter 是这一轮钉住的章节（请求里的 chapterId，intension 解析的）；named_chapter_order
    是他话里点名的章号，plan 拿这两个比一比，对不上就不动手。
    """

    novel: NovelMeta
    active_chapter: ChapterMeta
    chapter_review: ChapterReview
    target_chapter: ChapterTarget
    named_chapter_order: int
    edit_feedback: str
    user_message: str
    inspirations: list
    change_impact: list


class EditorOutput(TypedDict):
    """交回父图的：改出来的这一章（改设定的那一路不动它）、这次改动与它的影响台账、给人的回话。"""

    active_chapter: ChapterMeta
    setting_changes: list
    change_impact: list
    edit_note: str


class EditorState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    novel: NovelMeta
    active_chapter: Annotated[ChapterMeta, merge_chapter]
    chapter_review: ChapterReview
    target_chapter: ChapterTarget   # 这一轮钉住的章节（请求里的 chapterId）
    named_chapter_order: int        # 他话里点名的章号，plan 拿它跟 target_chapter 比
    edit_feedback: str
    user_message: str
    inspirations: list          # 用户这一轮挂上来的素材，plan 与 revise 都摆给他看
    materials: str              # 给 plan 的：设定目录 + 章节清单
    prev_past_summary: dict     # 给 summarize 的：上一章留下的前文总结，要并进新版
    redo: bool                  # 回炉这一趟：目标与"用户同意"都是现成的，不用再问
    plan: dict                  # 这一轮要改什么：plan 出类型与诉求，settle 补上 mode/targetId/fields
    target: dict                # 定位到的目标：设定那一行（含旧值）或章节那一行（含原稿）；新增的没有
    setting_changes: list       # 设定类要写的列（新增的整条），update 落库
    change_impact: list         # 影响台账的行，update 落库
    approve_text: str           # 摆给用户看的"改动 + 影响范围"
    edit_note: str              # 没改成的理由，update 拿它回用户一句话