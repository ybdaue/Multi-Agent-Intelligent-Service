"""novel 图的流式筛子：模型吐的 token 里，只有该给用户看的那段放行。

两个筛子，各自对着一个标记：

- `ProseFilter`：writer / editor 的回复是「正文 + 【本章台账】+ JSON」，还可能带了动笔前的
  分析。起点在【正文】之后、终点在【本章台账】之前。规则与落库端 `ledger.split_submission`
  同口径 —— 标记文字共用 ledger 的常量，不会两边各写一份，"用户看到的"与"存进库的"才是同一段。
  正文第一行还要按住读完整行：是标题（`# 第X章 标题`）就摘掉，落库端 `split_title` 摘的是
  同一行（标题只属于标题栏，正文里不留）。回炉（字数不合格、或用户要求再改）会让模型
  **重新发一次**【正文】，此时重发 `prose_start`，前端据此清空临时框重写 —— 是覆盖，不是追加。
- `SettingFilter`：开书 agent（agents/novel/setup）的回复是「散文 + 【设定项】标记块」，
  散文逐字发，标记块一个字都不发（用户看不见它）。切法整个交给 `settings.SettingScanner`
  —— 落库端 collect 算"给用户看的那句话"（`split_reply`）用的是同一份状态机，所以
  "发出去的 token 拼起来" == `split_reply` 的散文 == `interrupt` 问出去的那句话，
  是同一个东西的两种喂法，前端「流完再拿 question 整段替换」看不出跳变。

跨 chunk 的标记靠"末尾扣留几个字符"处理：标记被切成两半时，后半截还没到，那时不能急着发。
"""
import re

from agents.novel.utils.ledger import MARK, PROSE_MARK, TITLE_LINE

# 与 ledger.py 的 _PROSE / _MARK 同一套规则（那边是私有的，这边照抄样式；标记文字共用常量）。
# 起点的两条正则：_PROSE_LINE 要求标记在行首（含流的最开头），免得把分析里引用的
# 「要先写【正文】」误当成正文起点 —— 落库端 _PROSE 用的是 re.M 的 ^，行首语义一致。
_PROSE_LINE = re.compile(r"(?:^|\n)[ \t>*#-]*" + re.escape(PROSE_MARK) + r"[ \t*]*")
_MARK = re.compile(r"[ \t>*#-]*" + re.escape(MARK) + r"[ \t*]*")

# 扣留的尾巴长度：够藏住一个被切断的标记，也够藏住它前面的那个换行。
_RETAIN = max(len(PROSE_MARK), len(MARK)) + 1

# 正文第一行最多按住这么长还不换行，就当它不是标题行、照发 —— 标题没有这么长的，
# 再按住就成了把正文头一段扣着不发。
_HEAD_CAP = 120

# 丢弃段攒到这么长还没见着起点标记，就当这稿没写标记、把攒下的都当正文发出去。
# 模型漏写标记时这样还能有打字机效果（否则要等整轮跑完才整段蹦出来）；万一是分析写长了、
# 后面才补上标记，正文模式再把那个标记当成重新起头，前端清一次框就纠回来了。
#
# **兜底只在"还没切过台账"时作数**（见 feed 的 seen / cut_ledger）：切过台账说明后面攒起来的
# 这一段就是台账的 JSON —— 章越写越长、新造的角色越多，它就越容易超过上限，放出去等于把
# 台账原样打在用户的稿子里（还会先清一次框，看着像正文被换成了 JSON）。
_DISCARD_CAP = 800


def _find_start(buf: str, dropped: int):
    """在 buf 里找正文起点。标记连同它前面的换行、装饰符号一起算标记的一部分。

    buf 前面被裁掉过（dropped > 0）时，"^" 指的是 buf 开头、而不是流开头，那种假行首不作数。
    """
    for match in _PROSE_LINE.finditer(buf):
        if match.start() == 0 and dropped > 0 and not match.group(0).startswith("\n"):
            continue
        return match
    return None


class ProseFilter:
    """喂进 writer / editor 的 token 文本，吐出 [(事件名, 数据), ...]。

    prose_start 表示"接下来这段是正文的开头"（含回炉重写），token 是正文片段。
    feed 的 fresh 是"这一条 token 属于新的一条模型消息"：动笔前的寒暄（"我先读一下写手手册"）
    带着工具调用单独成条，跟交稿那条之间**没有换行**，粘在一个 buf 里会让行首的「【正文】」
    认不出来 —— 攒到上限就被整段当成正文发出去。消息边界就是换行边界，清空重找。
    """

    def __init__(self) -> None:
        self.buf = ""
        self.dropped = 0        # 已从 buf 前部丢弃 / 发出去的字符数，即 buf[0] 在流里的位置
        self.discarding = True  # 当前在丢：动笔前的分析，或台账那一段
        self.seen = False       # 是否出现过正文起点（决定 flush 时那段尾巴怎么处置）
        self.cut_ledger = False # 是否已经切过台账（切过就说明往后攒的全是那一段 JSON）
        self.head = False       # 正文第一行还没定性：标题行要摘掉，读完这行才往下发

    def feed(self, chunk: str, fresh: bool = False) -> list[tuple[str, dict]]:
        # 正在丢的时候换条消息 = 前面攒的那些都作废（它们要么是寒暄、要么是台账的 JSON），
        # 新消息的第一行就是真的行首。切过台账那一段也要清：字数不合格回炉重写是同一个
        # 回合里再调一次模型（writer 的 save 回到 write），不清的话重写的「【正文】」又被粘住，
        # 前端那边一稿都不重发，临时框里留着的是上一稿。
        if fresh and self.discarding:
            self.buf = ""
            self.dropped = 0
        self.buf += chunk or ""
        out: list[tuple[str, dict]] = []
        while True:
            if self.discarding:
                start = _find_start(self.buf, self.dropped)
                if start is None:
                    if not self._past_prose() and len(self.buf) > _DISCARD_CAP:
                        # 攒太久了还没见着起点标记，多半是模型没写：整段当正文起头往下发。
                        # 见过起点的、或已经切过台账的，都不走这条路 —— 那是台账的 JSON，丢掉。
                        # 交给下面那一段发（head 照样按住第一行）。
                        self.discarding = False
                        self.head = True
                        out.append(("prose_start", {}))
                        continue
                    break
                self._drop(start.end())
                self.discarding = False
                self.seen = True
                self.head = True
                out.append(("prose_start", {}))
                continue

            # 正文第一行先按住：那行可能是标题，读完这一行才知道摘不摘。
            if self.head and not self._settle_head():
                break

            # 正文模式：盯着台账（正文到此为止）和下一个起点（回炉重发），谁先到算谁。
            start = _find_start(self.buf, self.dropped)
            ledger = _MARK.search(self.buf)
            if ledger is not None and (start is None or ledger.start() <= start.start()):
                self._emit(out, self.buf[: ledger.start()])
                self._drop(ledger.end())
                self.discarding = True
                self.cut_ledger = True
                continue
            if start is not None:
                self._emit(out, self.buf[: start.start()])
                self._drop(start.end())
                self.head = True
                out.append(("prose_start", {}))
                continue

            # 标记可能被切断，尾巴先扣着；扣掉的那截是正文，发出去。
            self._emit(out, self.buf[: max(0, len(self.buf) - _RETAIN)])
            self._drop(max(0, len(self.buf) - _RETAIN))
            break
        return out

    def flush(self) -> list[tuple[str, dict]]:
        """流结束：扣住的尾巴补发。

        没出现过起点标记、也没切过台账就整段当正文（宁可多带一段分析，也不能把正文判没），
        但台账仍按标记截掉 —— 与 `split_submission` 退化成 `split_ledger` 的行为一致。
        另外两种（见过起点、切过台账）说明这段尾巴是台账那一段，丢掉。
        """
        if not self.buf:
            return []
        out: list[tuple[str, dict]] = []
        if self.discarding:
            if self._past_prose():
                self.buf = ""
                return out
            ledger = _MARK.search(self.buf)
            self.buf = self.buf[: ledger.start()] if ledger else self.buf
            self.discarding = False
            self.head = True
            out.append(("prose_start", {}))
        if self.head:
            self._settle_head(final=True)
        self._emit(out, self.buf)
        self.buf = ""
        return out

    def _settle_head(self, final: bool = False) -> bool:
        """正文第一行读完了没有；读完就把标题行摘掉（是标题的话）。

        读到换行就算读完；没读到换行但已经攒到 _HEAD_CAP，也当它不是标题（标题没这么长）。
        final 是流尾那一次：剩下多少都按"这一行读完了"算。返回假 = 还得再等几个 token。
        """
        cut = self.buf.find("\n")
        if cut < 0 and not final and len(self.buf) < _HEAD_CAP:
            return False
        line = self.buf if cut < 0 else self.buf[:cut]
        if TITLE_LINE.match(line):
            stop = len(self.buf) if cut < 0 else cut + 1
            while stop < len(self.buf) and self.buf[stop] == "\n":
                stop += 1        # 标题后面那串空行也是给它留的，一起摘
            self._drop(stop)
        self.head = False
        return True

    def _past_prose(self) -> bool:
        """这一波文本是否已经跟正文无关了（起点标记见过，或台账已经切过）。

        切过台账这一条不能少：模型漏写「【正文】」时正文是靠 `_DISCARD_CAP` 兜底放出去的，
        seen 一直是假；只认 seen 的话，台账后面那段 JSON 会被同一个兜底再放一遍 ——
        用户那边就是"正文写着写着突然变成一坨 JSON"，还会先清一次框。
        """
        return self.seen or self.cut_ledger

    def _drop(self, n: int) -> None:
        self.dropped += n
        self.buf = self.buf[n:]

    @staticmethod
    def _emit(out: list[tuple[str, dict]], text: str) -> None:
        if text:
            out.append(("token", {"text": text}))


class SettingFilter:
    """喂进开书 agent discuss 节点的 token 文本，吐出 [(事件名, 数据), ...]。

    只有 token 一种事件：散文逐字发，标记块（__SETTINGS__ 及其后的 JSON）一个字都不发。
    """

    def __init__(self) -> None:
        self._buf = ""
        self._done = False

    def feed(self, chunk: str) -> list[tuple[str, dict]]:
        if self._done:
            return []
        self._buf += chunk or ""
        # 查找 __SETTINGS__ 标记
        idx = self._buf.find("__SETTINGS__")
        if idx >= 0:
            before = self._buf[:idx]
            self._buf = ""
            self._done = True
            if before:
                return [("token", {"text": before})]
            return []
        # 还没碰到标记：全量发（标记最多被切成两半的边界情况：尾巴 12 字符扣住不放）
        hold = 12
        if len(self._buf) > hold:
            safe = self._buf[:len(self._buf) - hold]
            self._buf = self._buf[len(self._buf) - hold:]
            if safe:
                return [("token", {"text": safe})]
        return []

    def flush(self) -> list[tuple[str, dict]]:
        if self._done:
            return []
        # 流结束还没见着 __SETTINGS__：把扣住的都发出去
        text = self._buf
        self._buf = ""
        idx = text.find("__SETTINGS__")
        if idx >= 0:
            text = text[:idx]
        if text:
            return [("token", {"text": text})]
        return []
