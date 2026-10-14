"""改已存在的内容：读懂要改什么 → 定夺是并进哪条还是新增 → 列出可能受影响的 → 用户点头 →
改 → 交回父图。

八个节点：prepare 备料（回炉这一趟顺手整理好计划）、plan 出 JSON 计划、settle 定夺设定这一轮
是并进已有的哪一条还是新增一条（只有设定这一路走它）、impact 定位并算范围、approve 摆给用户
点头、revise 改正文、collect 收稿、summarize 刷新摘要。
editor 一个字都不落库，设定改动、影响台账、正文都由父图的 update 写（正文落库前还要过 reader
的审）。改哪一处、要不要问用户、下一步去哪都是必要流程，全在图里，模型只干三件事：读懂要改
什么、定夺并进还是新增、把正文改出来。

plan 与 settle 的分工是这次改出来的：plan 只看得到目录（id + 名字），看不见内容，让它挑一条
去改就是"挑一条最像的顶上去" —— 用户说"补充世界观"，它会把原有的那条盖掉。所以设定这一路
plan 只认类型 + 复述诉求，settle 把这一类现有的全部内容摆出来再定，撞不上就新增。

章节类把 chapter_id 置空当"本轮新交稿"的记号（reader 与 update 都认，跟 writer 的 save 同口径），
身份由 (novelId, order) 认，落库时 UPSERT 按这两列冲突更新、原 id 带回来。
子图对话不上交父图（父图 messages 后面要整段交给 intension / chat）。
"""
from .graph import editor

__all__ = ["editor"]