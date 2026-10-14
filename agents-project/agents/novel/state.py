from typing import List, Optional, TypedDict
from langgraph.graph import MessagesState

class NovelMeta(TypedDict):
    """小说级设定：load 从库里拉；库里没有就是一份空的（fromDB 为假，这本书还没建成）。

    开书（把这份设定从零收齐、落库）是「新建小说」弹窗里那个独立图的事，见 agents/novel/setup。
    大纲、世界规则、人物这些量大又按章生效的不在这里，由 ChapterMeta 按章取。
    """

    novel_id: str
    novel_title: str
    novel_word_count: int
    novel_tropes: str                    #小说套路
    novel_style: str                     #小说风格
    novel_review_enabled: bool           #是否开启 AI 审稿（reader 节点），关掉后写/改完直接到确认
    novel_outlines: List[dict]           #核心冲突（落 novel_outline 表，暂只一条）
    novel_world_rules: List[dict]        #世界观、等级/力量体系（落 novel_world_rule 表）
    novel_protagonists: List[dict]       #主角：人设、金手指、反差点
    fromDB: bool                         #这本小说是不是库里真有的，还是 load 补的空设定


class ChapterMeta(TypedDict):
    """当前正在写或改的这一章，按章节需要在用到时再查库填充。"""

    chapter_id: str
    chapter_title: str
    chapter_order: int
    chapter_status: str
    chapter_word_count: int
    chapter_summary: str                 #本章精简
    chapter_content: str                 #本章正文，只有改动已有章节时才取
    past_summary: dict                   #前文总结（前面章节讲了什么）
    chapter_state: dict                  #主角状态、故事内时间、事件进度、世界局势
    chapter_inspirations: List[dict]     #本章灵感
    # None = 这一稿没给台账（旧的关联一行不动）；[] = 明确说不涉及，换掉旧的。
    chapter_refs: Optional[List[dict]]   #本章用到的已有设定：[{refType, refId, role}]，落 novel_chapter_ref
    chapter_new: List[dict]              #本章新造的设定：[{refType, fields}]，先落各表再挂一条 ref
    # 本章所处的阶段线 / 支线：[{level, id, action, content, parentId}]，level 是 phase / branch。
    # open 时 id 是代码预生成的新 id、parentId 挂父（阶段线→主线、支线→阶段线）；continue/close
    # 照抄目标 id。由 update 写进 novel_outline；writer 没报就是 []。
    chapter_lines: List[dict]


class ChapterTarget(TypedDict):
    """这一轮钉住的章节：请求里的 chapterId 解析出来的那一章（见 nodes/intension.py）。

    用户开着哪一章，模型看不见 —— 它手上只有一份章节清单和用户说的话，所以"改一下这一章"
    这种话只能由请求来告诉图是哪一章。章号是给人看的，中间插进新章还会整体后移，别拿它当身份。
    """

    chapter_id: str
    chapter_order: int


class ChapterReview(TypedDict):
    """reader 对当前这一稿的结论，passed=True 即可直接落库。

    单留 passed 而不看 problems 空不空：模型会把「没问题」写成「无」。
    """

    passed: bool
    problems: str                        # passed=False 时逐条写清楚：第几处、错在哪、该怎么改


class SettingChange(TypedDict):
    """editor 定下的一处设定改动，落库在父图的 update。

    mode 分两种，白名单也是两份：
      update —— 改已有的一条，fields 只含要改的那几列，其余列原样不动，白名单是 EDIT_SPEC；
      create —— 新增一条，fields 是这一整条新设定，refId 为空，白名单是 NEW_ENTITY_SPEC
                （比 EDIT_SPEC 多 status，schema 里它是 NOT NULL）。
    """

    mode: str                            # update / create
    refType: str                         # character / faction / item / world_rule / timeline /
                                         # chronicle / foreshadowing / outline
    refId: str                           # create 时为空：这一行还没有 id
    fields: dict


class ChapterConflict(TypedDict):
    """用户这一轮点名要的写法，跟库里某条设定对不上。不算硬伤，交用户定夺。

    reader 查出来的：它对着大纲 / 世界规则 / 人物查「用户要的跟库里记的冲不冲突」。用户在
    确认时选了保留，这一条就变成一行影响台账落库（见 nodes/confirm_chapter.py）—— 库里那条
    设定实际已经被这一章偏离了，将来回头改它时得知道有这么一章对不上。
    """

    targetType: str                  # outline / world_rule / character ……，取值必须落在 ImpactTarget 里
    targetName: str                  # 库里那一条的名字 / 标题，拼进 reason 让用户看懂是哪条
    rule: str                        # 库里那条的口径 → 落 oldValue
    want: str                        # 用户要的写法 → 落 newValue


class ChangeImpact(TypedDict):
    """一行影响台账，键与 novel_change_impact 的列对齐（novelId 由落库那一步补）。

    只是"可能受影响"的候选，不是结论；severity 是启发式初值（见 utils/impact.py）。
    status / resolution 只有 reader 那条路给：那是用户当场点了「保留」才记下的行，
    落库就是 skipped（不是待处理的 pending），resolution 写清他做了什么决定。
    reader 审出的问题也走这一条：detectedBy="reader"，用户收下有问题的稿记 pending，
    重写后审过则同一批行翻成 fixed（见 nodes/reader.py 的 save）。
    """

    changeId: str
    changeSummary: str
    sourceType: str
    sourceId: str
    oldValue: str
    newValue: str
    targetType: str
    targetId: str
    targetChapter: Optional[int]
    reasonKind: str
    reason: str
    severity: str
    detectedBy: str
    status: str
    resolution: str


def merge_chapter(left: dict | None, right: dict | None) -> dict:
    """active_chapter 的 reducer：分几次写这一章时并起来（save 写全，summarize 再补两项）。"""
    return {**(left or {}), **(right or {})}


class State(MessagesState):
    # better-auth 的用户 id 是 cuid 字符串，库里 novel."userId" 也是 String，别当数字用。
    user_id: str = ""
    user_message: str
    intension: str

    # ===== 对话记忆 =====
    # 早先几轮压成的一段话（口径见 utils/history.py），和 messages 里最近几条一起喂给模型。
    chat_summary: str = ""

    # 这一轮用户在对话框里从灵感库挑中的灵感（/run 按 id 取回，完整行，带真 id）。
    # 每条 {id, title, category, type, content, usage, lifecycle, scenario, digest, usedChapterIds}：
    # 只取不落库 —— 灵感入库在灵感库那边做，这里只是点名用哪几条，落章后据此补 usedChapterIds。
    inspirations: List[dict]
    # 本章**最终选用**的灵感（planner 定：forced 必用 ∪ 本轮点名的那几条），带 how。
    # writer 照它的写作指引落笔，reader.style 逐条校验用没用上，update 落章后清空。
    chapter_inspirations: List[dict]

    # ===== 小说信息 =====
    novel: NovelMeta
    # 是否走 reader 审稿：load 时按 novel_review_enabled 读进 state，writer/editor 之后据此路由 ——
    # 关掉就直接去 confirm_chapter，用户确认后落库（见 __init__ 的条件边与 utils/classify）。
    review_enabled: bool = True
    # resolve 节点查好的上下文（前文、大纲、世界规则、设定目录），writer/reader 复用跳过重复查库
    writer_context: dict
    active_chapter: ChapterMeta
    # 这一轮钉住的章节（请求里的 chapterId，只有"改"这一路去解析）。空只有三种来路：这一轮
    # 不是"改"、他这会儿没在看某一章、开着的那章还没落库。改章节正文时拿不到它就直接拒不动手 ——
    # 落库要落在库里那一行真实的 id 上，不能靠模型认。
    target_chapter: ChapterTarget
    # 这一轮真正要落哪一章：resolve 定，随 SSE 的 target 事件下发给前端，让它在流的这一稿
    # 有归属（{kind, chapterId, order}）。**不等于** target_chapter：续写新章时后者是空的。
    target: dict

    # ===== 这一章的回炉闭环 =====
    # review 是这一稿的结论、attempt 是写了几稿；update 收尾时清掉，不能带到下一轮。
    chapter_review: ChapterReview
    # reader 查出来的"用户要的写法跟库里对不上"，确认时用户选了保留就记进影响台账。
    chapter_conflicts: List[ChapterConflict]
    chapter_attempt: int = 0

    # ===== 改已有内容（editor 那一路）=====
    # edit_feedback / setting_changes / change_impact 都由 update 落库，收尾时清空。
    edit_feedback: str = ""
    edit_note: str = ""                  # 这一轮没成的理由，update 拿它回用户一句话
    # 用户这一句话里点名的章号（intent 模型解析出来的，没点名就是 None）。只有"改章节正文"
    # 才拿它跟 target_chapter 比：对不上就不动手，别改了他没在看的那一章。
    named_chapter_order: Optional[int]
    setting_changes: List[SettingChange]
    change_impact: List[ChangeImpact]
