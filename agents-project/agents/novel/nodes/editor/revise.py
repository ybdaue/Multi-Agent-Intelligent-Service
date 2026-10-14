"""revise 节点：改稿 agent —— 照原稿与要求把这一章改出来（流式）。"""
from langchain.agents import create_agent

from ...tools import fetchDB, read_skill_file
from ...utils.prompt import EDIT_CHAPTER_PROMPT
from .helpers import _revise_main
from .state import EditorState

# 改稿照 writerSkill 写，挂跟 writer 一样的两件工具。问用户是 approve 的事，不挂工具；
# 也不挂"交稿"工具（正文与台账就是模型的回复，切开与落 state 是 collect 的事）。
# 开着流式：改出来的正文要逐字发给前端当打字机。台账由 api/novel/stream.py 的
# ProseFilter 在【本章台账】处截掉（与 writer 共用同一套标记与规则）。
_revise_agent = create_agent(
    model=_revise_main,
    tools=[read_skill_file, fetchDB],
    system_prompt=EDIT_CHAPTER_PROMPT,
    state_schema=EditorState,
)