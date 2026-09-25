# 小说服务架构：现状诊断与目标设计

> 核对时间：2026-09-22（对应提交 `version:2.0` 及其后的未提交改动）
> 范围：`agents-project/agents/novel/`、`agents-project/api/novel/`、`my-app/src/app/home/novel/`、
> `my-app/src/app/api/novel/`、`my-app/prisma/schema/novel.prisma`

---

## 0. 结论先行

现有后端是一套**控制流清晰、边界克制**的 LangGraph 双图（主图 + 开书图），提示词、台账、
流式筛子这几块质量很高，值得保留。真正让它"不好用"的不是模型，是三个架构性缺陷：

1. **草稿没有身份，靠"发请求时用户开着哪一章"来归属。** 前端把 agent 还在生成中的正文，
   直接画在用户发消息那一刻打开的那一章上（`NovelWorkspace/index.tsx:195` + `ChapterBody:96`）。
   agent 实际写的是第 N+1 章，界面却把它盖在第 N 章上 —— 这就是"生成内容覆盖了当前章节，
   刷新才恢复"。
2. **前端把库表当本地 state 使。** 正文编辑（`handleContentChange:519`）与删章
   （`handleDeleteChapter:499`）**只改 React 状态，没有任何落库请求**，后端也根本没有对应接口。
   刷新即丢，用户看到的就是"刷新后从数据库拿数据才恢复正常"。
3. **"写什么"这个决策只有一次 LLM 三分类。** `write / edit / chat` 一个标签决定走哪张子图，
   而"续写这一章""把这章扩一扩""在中间插一章""生成新内容"全被折叠进两个动作里，
   且写新章之前没有任何确认步骤（editor 有 `approve`，writer 没有）。

目标架构一句话：**把「写作任务 + 草稿」升为一等公民，带着显式目标（哪本书、哪一章、什么动作）
走完全程；前端分成「库数据 / 会话 / 视图」三层，库是唯一真相。**

---

## 1. 现状架构

### 1.1 三层进程

```
浏览器 (my-app, :3000)
  └─ Next Route Handler（BFF）：withAuth 鉴权 → 带 Bearer 转发 → SSE 原样透传
       ├─ POST /api/novel/agent/{run,resume}   → 后端 /api/novel/agent/*   （写章主图）
       ├─ GET  /api/novel/agent/{pending,history} → 后端同名口子（重建现场）
       ├─ POST /api/novel/agent/clear          → 后端（清对话）
       ├─ POST /api/novel/setup/{run,resume}   → 后端 /api/novel/setup/*   （开书图）
       └─ GET  /api/novel/method/[...path]     → 后端 /api/novel/method/*  （白名单 13 个只读口）
后端 (agents-project, :8080)
  ├─ api/novel/agent.py   主图 HTTP + SSE + /pending /history /clear
  ├─ api/novel/setup.py   开书图 HTTP + SSE
  ├─ api/novel/method.py  书架 / 正文 / 各类设定 / 台账 / 影响清单（只读）+ 3 个写口
  └─ agents/novel/        LangGraph 图与节点
PostgreSQL（my-app 的 Prisma 库）：novel* 表 + checkpoint + agent_store
```

### 1.2 数据模型（`novel.prisma`，418 行，20 张表）

围绕一本书展开：

- **`novel`** — 书：title / wordCount / tropes / style。
- **`novel_chapter`** — 章：`(novelId, order)` 唯一，title / status / content / summary /
  pastSummary / wordCount。
- **九类设定** — `novel_character` / `novel_faction` / `novel_item` / `novel_outline` /
  `novel_world_rule` / `novel_timeline` / `novel_chronicle` / `novel_foreshadowing` /
  `novel_inspiration`。多数带 `startChapterId / endChapterId` 圈生效区间。
- **`novel_chapter_ref`** — 台账：这一章**用到/提到**了哪些已有设定（`(chapterId, refType, refId)` 唯一）。
- **`novel_change_impact`** — 改动影响台账：一次设定改动的候选波及面，`changeId` 分组。

设计亮点：**台账表把"改设定会波及哪些章节"从 N×M 的映射表变成了可反查的平铺行**，
这个取舍是对的，保留。

### 1.3 主图 `novel_agent`（`agents/novel/__init__.py`）

```
START → intension ─┬─ write → load → writer ─┐
                   ├─ edit  → load → editor ─┼→ reader → confirm_chapter ─┐
                   └─ chat  → chat ──────────┴─(还压着未确认的稿)─────────┘
                                                                          ↓
                             update ←──────────────(收下/改)──────────────┘
                               ↓
                             compact → END
```

- `intension`（`nodes/intension.py`）：一次 `intentModel` 调用出 `{intension, chapterOrder}`；
  只有 `edit` 这一路会把请求里的 `chapterId` 解析成 `target_chapter`。
- `writer`（`nodes/writer.py`）：子图 `prepare → write(create_agent) → save → summarize`。
  **`save` 里序号由 `next_chapter_order()` 现算（`max(order)+1`），写新章永远追加在末尾。**
- `editor`（`nodes/editor.py`，711 行）：子图 `prepare → plan → [settle] → impact → approve →
  revise → collect → summarize`。改章节正文只能改**用户在请求里开着的那一章**；改设定走
  `plan(类型+诉求) → settle(拿这一类全部内容定"并入/新增") → approve`。
- `reader`（`nodes/reader.py`）：子图 `gather → quiz → check → save`，出审稿结论与
  "用户要的跟库里对不上"的 `conflicts`。
- `confirm_chapter`（`nodes/confirm_chapter.py`）：`interrupt` 问用户收下还是改；
  用户不点按钮而是问话时，转 `chat` 答完再回到这一问。
- `update`（`nodes/update.py`）：**唯一的落库点** —— 章节 upsert + 设定改动 + 影响台账。

**判定"这一轮有没有新交的稿"的唯一口径**：`active_chapter.chapter_content` 非空
且 `chapter_id` 为空。reader / confirm_chapter / update / route_after_chat 四处都靠它。

### 1.4 前端

`NovelWorkspace/index.tsx` 单文件 860 行，一个 state 树装下全部：

```
novels[]        ← 书架 + 章节列表 + 每章 content（镜像一个库表）
activeRun       ← 本轮生成：{novelId, chapterId, draft, stage, pendingQuestion, options}
chats{}         ← novelId → 消息气泡
ledgerChapter / tab / 各类弹窗
```

与后端的状态对账靠两条只读口：`GET /agent/history`（对话）与 `GET /agent/pending`
（有没有一份交了没确认的稿 + 那一稿正文 + 那一问 + 按钮）。这一层设计是完整且必要的：
**草稿只活在 checkpoint 快照里，刷新后前端手上什么都没有，只能问后端。**

### 1.5 一次「在已有章节里让 agent 生成」的时序（问题现场）

```
用户在 第3章（库里已有） 输入"生成新内容"
  └─ handleSend(chapterId = ch3.id)                      NovelWorkspace:672
       setActiveRun({chapterId: ch3.id, ...})            ← 记住的是"发请求时开着的那一章"
       POST /agent/run { novelId, text, chapterId: ch3.id }
  └─ 后端 intension = "write"（提示词规则 1：会多出一章才算 write）
  └─ writer.prepare → get_writer_context(order=None) → order = max+1 = 4
  └─ writer 写完第4章，SSE 逐字下发 token
  └─ 前端 onProseStart / onToken → activeRun.draft 累积
       draft = (runHere.chapterId === activeChapterId) ? draft : null   :195
       → ch3.id === ch3.id → 正文区把第3章的内容换成第4章的草稿      ChapterBody:96
```

界面表现：**第3章被"覆盖"了。** 只有等到 `confirm_chapter` 落库走完 `onFinal`
（`:748` 认出 `intension === "write"` 且章 id 变了 → 重拉书架并切到第4章）才自我纠正；
中途刷新则因为库没动，第3章原样回来 —— 于是"刷新就恢复正常"。

---

## 2. 问题诊断

### P0-1 草稿归属靠猜（你报的主症状）

前端 `ActiveRun.chapterId` 语义是**请求发起时所在的章**，但渲染时把它当成了**产物的归属章**。
两者在"write"这一路必然不同：

- 归属章由 **writer 在 `save` 里算的 `next_chapter_order`** 决定，前端在流式期间根本不知道；
- 后端也知道，但**直到 `onQuestion` / `onFinal` 才通过 `landDraft` 告诉前端**（`:564`），
  而且 `landDraft` 还是靠**正则解析章节标题**去认领草稿的（`chapterOrderOf:95`，`/第\s*(\d+)\s*章/`）——
  标题一旦没按模板写、或库里已有同名序号，就认错。

→ 在流式的整段时间里（往往几十秒）界面是错的；用户这时最容易下判断"它把我的章盖了"。

### P0-2 前端把库表当本地 state（你报的"刷新才恢复"）

| 操作 | 前端 | 后端接口 | 结果 |
|---|---|---|---|
| 改正文 | `handleContentChange:519` 只 `setNovels` | **不存在** | 刷新即丢 |
| 删章 | `handleDeleteChapter:499` 只 `setNovels` | **不存在** | 刷新即回来 |
| 改章名 | `handleRenameChapter:443` 只 `setNovels` | **不存在** | 刷新即丢 |
| 改章状态 | 乐观改 + POST `/chapter/status` | 有 | 正常 |
| 改书名 | POST `/novel` | 有 | 正常 |
| 传灵感素材 | `AiPanel:76` → 只用来渲染气泡 | **不存在** | agent 根本收不到 |
| 改类型 / 文风 | 无入口 | **不存在**（只在开书写一次） | 改不了 |
| 看总字数 / 类型 / 文风 | `types.ts:31` 把三个字段丢了 | 返回了（`method.py:184`） | 用户看不到 |

`method.py` 只提供三个写口：`/chapter/status`、`POST /novel`（改名）、`DELETE /novel`。
**正文编辑与删章是纯前端幻觉。** 这直接解释了"agent 不好处理修改内容"的另一半体感：
用户手改的内容根本没进库，agent 下一轮读的还是旧正文，两边自然会打架。

### P0-3 "写什么"只有一个 LLM 三分类，且写新章无确认

`INTENT_PROMPT` 把"会不会多出一章"当唯一准绳，于是：

- "续写这一章""把这章补完" → `edit` → 走 editor 的**整章重写**（模型重发全文，
  哪怕只改一处，也是全章重来；`EDIT_CHAPTER_PROMPT` 明确要求"整章不是片段"）；
- "在中间插一章""写第 5 章" → 没有对应动作。`write` 只会追加到 `max(order)+1`，
  想插到中间或指定序号，做不到；
- 写新章**没有 `approve`**：editor 改设定前会摆出方案请用户点头，writer 则是闷头写完一章
  再问"收下吗"。意图判错一次的代价是一整章 token + 用户等待。

### P1 其他

- **`active_chapter` 是跨轮存活的全局缓存**，没有身份也没有版本。四个节点靠
  "`chapter_id` 空不空"这一条约定去猜它是不是本轮新稿；一次语义偏差就全线误判。
- **对话与"待确认问题"混在 `messages` 里**，于是要用 `_carried`（`confirm_chapter:54`）、
  `last_reply`、`_history` 的字符串前缀比对（`agent.py:178-190`）去做去重。这类启发式
  是"看起来能用但每加一个分支就更脆"的典型。
- **两端共写一库、手写 SQL 与 Prisma 漂移**：`novel.prisma` 是 schema 权威，
  但 `method.py:_COLUMNS`、`ledger.NEW_ENTITY_SPEC`、`impact.EDIT_SPEC` 三处各自列了一遍
  列名与白名单，加一列要改三处。
- **无并发/版本控制**：`novel_chapter` 只有 `(novelId, order)` 唯一约束，正文按整份覆盖 upsert。
  agent 落库与用户手动编辑（将来做了保存）之间没有 `updatedAt` 校验，后写覆盖前写。
- **章号是展示用的，却被当身份用**：`named_chapter_order`、"第 N 章"标题正则匹配、
  `order` 做 upsert 键 —— 中间插入一章后整体后移，这些地方都会错位。文件名/注释里其实
  已经认识到"章号中间插新章会整体后移，别拿它当身份"，但实现只做了一半。

### 根因归纳

> 后端把**控制流**收进了图（对的），前端却把**数据流**留在了组件里；
> 而"这份草稿属于哪一章"这件事，两端都没有一个显式的、可传递的字段承载它 ——
> 后端在 `save` 时临时算出一个序号，前端只能靠"发请求时开着哪一章"去猜。

---

## 3. 目标架构

### 3.1 四条原则

1. **库是唯一真相**：任何"用户能看到、刷新后还在"的东西必须先落库。前端只持有两类临时态：
   未保存的本地编辑、以及一个带显式归属的在跑任务。
2. **目标先解析、后动笔**：动作（写/改/插/扩）与目标（哪一章、什么序号）由图里的确定性节点
   从**请求参数 + 库**推出，不让模型认，也不让前端猜；解析结果**在任何 token 之前**就发给前端。
3. **必要流程由图的边决定**（沿用现有原则）：只有"用户想怎么改"交给模型。
4. **一份数据一个归属**：草稿是独立资源（`Draft`），挂着自己的 `taskId` 与目标；
   它不再"借用"某一章的渲染槽位。

### 3.2 领域模型：把 Task / Draft 提出来

这是整个重构的支点。现在散落在 `ActiveRun`、`active_chapter`、`/pending` 里的东西，
合并成一个显式对象：

```python
# agents/novel/state.py（目标态）
class TaskTarget(TypedDict):
    kind: str            # write_next | write_at | insert_after | extend | rewrite | edit_setting
    chapter_id: str      # 库里已有的目标章；写入新章时为空
    order: int | None    # 展示用序号；写新章时由 resolve 定死，前端据此画"第 N 章草稿"

class Draft(TypedDict):
    task_id: str
    kind: str
    target: TaskTarget
    title: str
    content: str
    summary: str
    refs: list | None    # None = 这稿没给台账
    new: list
    review: ChapterReview
    conflicts: list[ChapterConflict]
    status: str          # streaming | awaiting_user | applied | discarded
```

主图 state 里 `active_chapter` 拆成两个字段：

- `draft: Draft` —— 本轮交的、还没落库的稿（等价于现在"`chapter_id` 为空"那一路，
  但带着显式 target）；
- `last_applied: {chapter_id, order}` —— 上一轮落库成功的章，供 update 回话用。

"是不是本轮新稿" 的判据从 `chapter_id 为空` 变成 **`draft.status in (streaming, awaiting_user)`** ——
语义显式，不再靠约定。四个节点的守卫同步改这一处。

### 3.3 后端：`resolve` 节点 —— 目标先定，再动笔

在 `intension` 位置放一个 `resolve` 节点，职责收敛为：

```
输入：请求参数 {action?, chapterId?, order?} + user_message + 库
输出：TaskTarget（确定性），并立即通过 SSE 下发 `target` 事件
```

- **前端显式动作优先**：用户在界面上点"写下一章""改写本章""在下面插入"时，
  `action` 直接随请求带上，`resolve` 不再调模型。
- **自由文本**才走意图分类，且分类结果要**与请求参数交叉校验**：
  - 分类出 write 家族但用户正开着第 3 章 → 目标 = `write_next` 到第 4 章，**并把第 4 章这个
    目标立刻播给前端**（不再让前端猜）；
  - 分类出 edit 且请求带了 `chapterId` → 目标是那一章；用户话里点的章号与 `chapterId`
    对不上时（现有 `_conflict_text` 逻辑）在 `resolve` 就 `interrupt` 问清，别等到写了一半。
- **写新章前默认确认（可配置关闭）**：给 `write_*` 加一次轻量 `interrupt`
  （"准备写第 4 章，接着第 3 章往下；开始/换一章？"），**默认开**，熟手可在设置里关掉。
  这一步不花 token，却把"意图判错要白写一整章"的成本降到零。**已拍板**。

`resolve` 之后的条件边：

```
resolve ─┬─ write_next | write_at | insert_after → writer → reader → confirm_chapter
         ├─ extend | rewrite                     → editor → reader → confirm_chapter
         ├─ edit_setting                         → editor_setting → approve → apply
         └─ chat                                 → chat
                                                    ↓（都汇到）
                                                  apply → compact → END
```

改动要点：

- **`writer` 接收 target.order**（新增 `write_at`、`insert_after`）。`save` 不再无条件
  `next_chapter_order()`；`write_next` 仍算 max+1，`write_at(order)` 用指定序号，
  `insert_after(chapterId)` 走"序号后移 + 插入"的事务。序号永远是**节点按 target 定的**。
- **`extend`（续写已有章）成为独立动作**：这是用户心智里最自然的"在这一章生成新内容"。
  实现上让 revise agent 只输出**续写段落**，由 `collect` 拼接到原正文尾部（或按指令插入到
  指定锚点），而不是整章重发。这样"只加一段"真的只花一段的 token，也不会顺手改掉别处。
  **两条连带义务（否则会静默损坏影响分析）**：
  1. 台账必须**增量挂**，不能整批重写。`ledger.write_ledger` 现在是"先 `DELETE` 这一章全部
     ref、再按本稿写新的"；extend 这一稿只报了新增段落用到的设定，照旧路走会把这一章原有的
     关联全删掉 —— 那些章从此在影响分析里查不出来（反查 `novel_chapter_ref` 是唯一底账）。
     extend 走 merge：只 upsert 本稿报的 ref，不删旧的。
  2. 摘要必须刷新。`summary` / `pastSummary` 是 writer 的 `summarize` 产的，正文变了它就旧了；
     下一章的写手会读到一段与正文不符的"前文总结"。extend 之后要重跑一次 summarize。
- **`editor` 的选章逻辑从 plan 里搬走**：现在 `plan` 输出 `targetType: chapter` 后由
  `target_chapter` 补序号（`editor.py:348`），改成 `resolve` 直接给 `target.chapter_id`，
  editor 只管"怎么改"。
- **`confirm_chapter` 的落库改为 `apply` 节点的显式分支**：`keep` → `apply_draft(draft)`；
  `revise` → 回写手/改写手。`apply_draft` 按 `draft.target.chapter_id or order` 落库，
  天然区分"改已有章"与"写新章+插入"。

### 3.4 对话与提问分离

- `messages` 只放**真实对话**（用户说的、助手答的）。
- 待确认的问题挂在 `draft.question / draft.options` 上，不写进 messages。
- 于是 `/history` 不再需要 `_carried` 那套前缀比对；`/pending` 直接返回
  `{pending, task: Draft, question, options}`，无启发式。

### 3.5 前端：三层收敛

把 860 行的 `NovelWorkspace` 拆成三条独立的关注点：

```
useNovels(userId)                // 书架 + 章节元数据（不含 content），SWR 式缓存 + 失效
useChapter(novelId, chapterId)   // 按 id 取正文；提供 save(content) 落库（带版本校验）
useNovelSession(novelId)         // messages + activeTask{target, draft, question, options}
                                 // 由 SSE 增量 + /history + /pending 冷启动组装
```

关键改动：

1. **正文不再塞进 `novels[].chapters[].content`**，改由 `useChapter` 按 id 取，
   编辑走 `save` 落库（补后端 `POST /chapter/content`，带 `updatedAt` 乐观并发校验）。
   这一步同时修好"手改正文刷新即丢"。
2. **删章补后端 `DELETE /chapter`**（事务里重排序号、级联 `novel_chapter_ref`）。
3. **渲染归属由 `activeTask.target` 决定**，不再是 `runHere.chapterId === activeChapterId`：

   ```tsx
   // 目标是一章已有章：只在"正看着那一章"时把草稿渲染在它的槽位（并明确标"生成中/待确认"）
   // 目标是新章（chapter_id 为空）：草稿渲染成一个独立的"第 N 章 草稿"条目，
   //   由 SSE 的 target 事件当场创建，序号来自 target.order，不解析标题
   draftSlotFor(chapter, activeTask)   // ← 纯函数，可单测
   ```
4. **SSE 增加 `target` 事件**（`{kind, chapterId, order}`），`useNovelAgent` 处理它并在
   任何 token 之前就把 `activeTask.target` 定下来。`landDraft` / `chapterOrderOf` 的正则匹配删除。

### 3.6 API 契约（目标态）

```
POST /api/novel/agent/run     { novelId, text, action?, chapterId?, order? }
POST /api/novel/agent/resume  { novelId, taskId, answer }        # 带 taskId，防串轮
GET  /api/novel/agent/task    ?novelId                            # 取代 /pending，返回完整 Draft
GET  /api/novel/agent/history ?novelId
POST /api/novel/agent/clear   { novelId }

POST   /api/novel/method/chapter/content  { novelId, chapterId, content, baseUpdatedAt }  # 新增
DELETE /api/novel/method/chapter          { novelId, chapterId }                          # 新增
POST   /api/novel/method/chapter/reorder  { novelId, chapterId, toOrder }                 # 可选
```

SSE 事件（主图）：

```
session → target → stage → prose_start → token… → question | final → done
                     └ 回炉重写再发 prose_start（沿用）
```
`target` 是新增的唯一事件，其余协议不变 —— 前端解析器只加一个 case。

### 3.7 落库收口

- 新增 `agents/novel/store.py`：把 `chapter_information` / `ledger` / `impact` 里散落的
  SQL 收成一组**按领域命名**的函数（`get_chapter` / `apply_draft` / `update_chapter_content` /
  `delete_chapter` / `write_ledger` / `write_edits`）。节点只调 store，不写 SQL。
- **列清单只留一份**：`EDIT_SPEC` / `NEW_ENTITY_SPEC` / `_COLUMNS` 三处重复的白名单，
  收敛到 `schema_fields.py` 生成，或直接从 Prisma schema 导出 JSON 供 Python 读。
- `apply_draft` 与"手动保存正文"都带 `updatedAt` 校验；冲突时返回 409，前端提示
  "这章已被 AI/另一个标签页改过，请先刷新"。

### 3.8 分层与迭代边界（"架构分明、可以迭代"的保证）

四个层各自只依赖下一层的接口，可以独立演进：

| 层 | 位置 | 对外接口 | 能怎么改而不动别人 |
|---|---|---|---|
| 提示词 | `utils/prompt.py` | 无（被节点调用） | 改写作质量、加体裁/风格，不碰图与前端 |
| 图（控制流） | `nodes/*`、`__init__.py` | **SSE 事件协议** | 加动作（插入 / 拆章）、调确认点；前端只需认识新事件 |
| 数据访问 | `store.py`（新） | 领域函数 | 换 SQL、加缓存、换库；图与前端无感 |
| 前端视图 | `hooks/` + 组件 | hook 返回值 | 换 UI、拆组件；不认识 SQL，也不认识图 |

**只有三个契约**，改它们才算破坏性变更：

1. **SSE 事件名与载荷**（`session / target / stage / prose_start / token / question / final / error / done`）；
2. **`Draft` 的形状**（`taskId / kind / target / title / content / refs / new / status`）；
3. **章节的身份是 `chapterId`**，`order` 只用于展示与排序。

守住这三条，上面四层可以各自迭代 —— 这也是本方案相对现状最大的收益：现状里
"加一个动作"要同时改提示词、图、`api/novel/agent.py` 的事件拼装、前端渲染归属四处。

---

## 4. 分阶段落地（按主流场景的收益排序）

排序依据是**大多数用户每天真正会走的路径**：写新章 > 改/续本章 > 问章节 > 手改正文。
先修这条主路上会摔的坑，其余（并发、多标签页、插章）属于加固。
括号里的 § 号是 §7 里对应的缺口设计。

### P0 —— 止血：主路上必摔的坑（改动小，不动图结构）

1. **草稿归属显式化**：`resolve` 后立刻下发 `target` 事件，前端 `activeTask.target`
   在流式开始前定死；渲染从"发请求时开着哪一章"改成"按 target 归属"。
   → 修掉"生成内容覆盖当前章节"（§6.5 第 2 条，最高频）。
2. **补齐落库写口**：`POST /chapter/content`、`DELETE /chapter`、`PATCH /chapter`（改名），
   以及把 `POST /novel` 扩成 `PATCH /novel`（书名 / 类型 / 文风）；前端对应的
   `handleContentChange` / `handleDeleteChapter` / `handleRenameChapter` 改为落库（编辑加防抖）。
   → 修掉"刷新即丢"（§6.5 第 6/7/8/18 条，§7.7）。
3. **把小说信息还给用户看**：`Novel` 类型补上 `wordCount / tropes / style` 并显示出来。
   纯前端，后端早就返回了（§7.13）。→ 修掉 §6.5 第 17 条。
4. **把"断开后怎么办"定下来**（§7.11 三选一，建议选"明确失败"），
   顺带把 `stop()` 暴露出去（§7.10）。→ 修掉"刷新一下刚写的全没了，也没报错"。
5. 保留 `active_chapter` 与 `intension` 不动（这一阶段只改"归属的表达方式"），风险最低。

### P1 —— 动作显式化 + 数据真的接通（主路体验的第二段）

5. `TaskTarget` + `Draft` 进 state，`resolve` 取代 `intension` 的定位职责；
   `writer` 支持 `write_at` / `insert_after`；`extend` 独立成动作（只输出续写段落）。
   连带：`extend` 走**台账 merge**（不 DELETE 旧 ref）+ 重跑 `summarize`（§7.3）。
6. **`chat` 接上图内只读取数**：复用现成的 `tools/fetchDB.py`（已有 15 张表的只读查询），
   让"问某一章写了什么 / 某个设定是什么"能读到**已落库**的内容。→ 修掉 §6.5 第 10 条（§7.2）。
7. **灵感素材真的送达**：`/run` 带上附件，并落 `novel_inspiration`。→ 修掉 §6.5 第 9 条（§7.8）。
8. `messages` 与"待确认问题"分离，删掉 `_carried` / `last_reply` 去重；
   前端把"写下一章 / 续写本章 / 在此后插入 / 改设定"做成显式按钮（自由文本仍走分类）。

### P2 —— 收口与加固（非主流路径，但迟早会疼）

9. `store.py` 收 SQL；`EDIT_SPEC` / `NEW_ENTITY_SPEC` / `_COLUMNS` 列清单收敛成单一来源。
10. 正文保存的乐观并发：`apply_draft` 与手动保存都带 `baseUpdatedAt`，冲突返回 409（§7.4）。
11. `novel_task` 表（把在跑任务落库，取代快照读）；其上的唯一部分索引顺带当**单飞锁**（§7.5）。
12. 受影响点的处理写口（§7.9）；插章 / 删章的级联对齐（§7.12）；
    `useNovels` / `useChapter` / `useNovelSession` 三层拆分；`write_*` 的"目标确认"开关。

---

## 5. 验收清单（把这次的症状固化成回归用例）

按主流路径从上到下排列；★ = 最高频，P0 就要过。

| # | 场景 | 期望 |
|---|---|---|
| 1 | ★ 开书：确认设定 → 开篇 | 开书图存完设定，主图能接着同一本书写第1章；设定不丢、不重问 |
| 2 | ★ 打开第3章，说"写下一章" | 第3章正文纹丝不动；界面出现**独立的**"第4章 草稿"并流式增长；回到第3章仍显示原文 |
| 3 | ★ 同上，中途刷新 | 恢复出同一个"第4章 草稿"与那一问；第3章仍是原文 |
| 4 | ★ 说"续写这一章" | 只产出续写段落拼到尾部；其余段落逐字未变；台账只增不删；摘要被刷新 |
| 5 | ★ 问"第3章里他为什么走" | 读出**已落库**正文作答，不是"我不知道" |
| 6 | ★ 在第3章手动改一段 → 刷新 | 改动还在（已落库） |
| 7 | 生成完一章后问一句 | 先答，再重摆"收下/改"那一问；稿子未确认前不落库 |
| 8 | 说"这章不行，重写"（回炉） | 带原反馈重跑，旧稿作废，不落库 |
| 9 | 改一个设定 | 先摆方案请点头；落库后受影响点可查 |
| 10 | 删一章 → 刷新 | 那一章确实没了，序号连续 |
| 11 | 说"在第2章后面插一章" | 新章 order=3，其后序号后移，正文未丢 |
| 12 | 落库与手动编辑并发 | 后写者拿到 409 而不是静默覆盖 |
| 13 | ★ 给一章改标题 → 刷新 | 标题还在（已落库），章列表与正文区标题一致 |
| 14 | ★ 传一张参考图说"照这个感觉写" | agent 真的拿到了这张图，不是只在前端气泡里挂着 |
| 15 | ★ 生成到一半点"停止" | 流停住、稿不落库，可以重新提要求；不是只能刷新 |
| 16 | ★ 流式途中刷新 / 断网 | 行为**明确**：要么这一轮标记为失败可重试，要么能接回来；不允许"悄悄没了" |
| 17 | 受影响点标"已跳过" → 刷新 | 还是"已跳过"（状态已落库） |
| 18 | 删 / 插一章之后看设定面板 | 人物、世界规则等"生效区间"跟着对齐，不指向已不存在的章 |
| 19 | ★ 打开一本书 | 看得到"共 N 字 · 类型 · 文风"，且字数与各章之和一致 |
| 20 | ★ 改这本书的类型 / 文风 → 刷新 | 改动还在；之后写的章按新文风走（writer 读的就是这两列） |

---

## 6. 主流场景 × 前后端分工（"怎么设计更好"的正面回答）

### 6.1 一条总原则：界线画在"有没有跨请求生命周期"

- **活过刷新的东西，家在后端**（库 + 图）：一本书、一章正文、一个在跑的任务、
  一份没确认的草稿。它们要跨请求、跨标签页存在，只能有一个家。
- **刷新即丢的东西，家在前端**：当前打开哪一章、切到哪个标签、输入框里没发出去的半句话。
  丢了是**正确行为**，不用抢救。

现有代码把这条界线画反了两处 —— 本该落库的正文编辑留在了前端（P0-2），
本该前端即时决定的"草稿画在哪一章"却要问后端、还只能靠正则猜（P0-1）。
重构就是**把这两处对调回来**。

### 6.2 后端：三个一等对象

| 对象 | 家 | 生命周期 | 谁写 |
|---|---|---|---|
| `Novel` + `Chapter`（含正文） | PG 表 | 永久 | 图节点 / 手动保存接口，都要过 `updatedAt` 校验 |
| `Task`（在跑的一轮） | `novel_task` 表 | 一次请求 | `resolve` 建，`apply` 结 |
| `Draft`（没确认的稿） | `novel_task.draft` | 到用户点头为止 | writer / editor 产，`apply` 消费 |

关键点：**`Draft` 带着自己的 `target` 和 `taskId`**，所以"这稿是谁的"是一份数据，
不是一条注释或一个约定 —— 现在四处靠 `chapter_id 为空` 猜的写法全部消失。

### 6.3 前端：一次请求只认一个 `target`

- `useNovels`：书架与章节目录（**不含正文**），SWR 式缓存。
- `useChapter(novelId, chapterId)`：按 id 取正文 + `save()` 落库（防抖 + `baseUpdatedAt`）。
- `useNovelSession(novelId)`：`messages` + `activeTask{target, draft, question, options}`，
  由 SSE 增量与 `/task`、`/history` 冷启动拼出。
- 渲染是**纯函数**：`draftSlotFor(chapter, activeTask)` 决定草稿落在哪 ——
  target 是已有章 → 落那一章的槽位；target 是新章 → 单起一个"第 N 章 草稿"条目。
  可单测，不再依赖"发请求时开着谁"。

### 6.4 逐场景对照

| 场景（频次） | 后端做什么 | 前端做什么 |
|---|---|---|
| 开书 → 开篇（★） | `setup` 存设定；主图对同一 `novel_id` 写第1章 | 弹窗关闭后进工作台，直接"写第一章" |
| 写下一章（★） | `resolve` 定 `write_next` / `order=max+1`，先播 `target` | 用 `target.order` 起"第 N 章 草稿"，不动当前章 |
| 续写本章（★） | `extend`：只产续写段落，台账 **merge**，事后重跑 `summarize` | 草稿显示在**该章槽位下方**，可对照原文 |
| 问章节内容（★） | `chat` 挂 `fetchDB` 只读工具，能读已落库正文 | 普通气泡，无需特殊处理 |
| 手改正文（★） | 新增 `POST /chapter/content`，带 `baseUpdatedAt` | `useChapter.save()` 防抖落库 |
| 确认阶段提问 / 回炉 | `confirm_chapter` 转 `chat` 答后回到那一问；`revise` 作废旧稿 | 问题与按钮由 `activeTask.question/options` 驱动 |
| 改设定 | `plan → settle → impact → approve`（保留，设计已对） | 面板展示受影响点；入口走对话 |
| 删章 / 插章 | `DELETE /chapter`（事务重排序号）；`insert_after` 后移 | 删完重拉目录；插章用 `target` 起草稿 |
| 受影响点 | `novel_change_impact` 反查（保留） | 只读展示，改动后失效重拉 |

### 6.5 用户视角全生命周期核对（逐条对过代码）

不看模块看用户：把一个人从开书到改稿会说的话按顺序走一遍，逐条给出**今天到底行不行**。
✅ = 现在就能用；⚠️ = 能用但有坑；❌ = 做不到或者会丢东西。依据都指到代码行。

| # | 用户会说 / 会做 | 今天 | 卡在哪（代码证据） |
|---|---|---|---|
| 1 | 刚建好书，想直接开篇 | ⚠️ | `setup/save` 只存设定不建第1章，得回工作台再说一句"写第一章"（§7.1） |
| 2 | 打开第3章说"写下一章" | ❌ | 第3章被第4章的草稿盖住，刷新才恢复（`NovelWorkspace:195` → `ChapterBody:96`） |
| 3 | 同上，写到一半刷新 | ❌ | `/pending` 只认"有稿 + 有问"，流式期间两者都还没有（`agent.py:316`）；且客户端断开会让服务端 `astream` 被取消，半截正文连快照都没落 |
| 4 | 写偏了想停下 | ❌ | `useNovelAgent` 不对外暴露 abort，`busy` 只是禁用输入；只能刷新 |
| 5 | 说"续写这一章" | ⚠️ | 归到 `edit`，editor 要求**整章重发**（`EDIT_CHAPTER_PROMPT`），不是只加一段 |
| 6 | 在正文框里手改一段 | ❌ | `handleContentChange:519` 只改 React state，后端没有对应接口 |
| 7 | 给一章改个标题 | ❌ | `handleRenameChapter:443` 只改 React state（漏网的第 3 处） |
| 8 | 删掉一章 | ❌ | `handleDeleteChapter:499` 只改 React state（`method.py` 只有 3 个写口） |
| 9 | 传一张参考图说"照这个写" | ❌ | `AiPanel:76` 把附件交给 `onSend`，但 `run()` 的请求体里**根本没有附件**（`useNovelAgent:239`），agent 看不见 |
| 10 | 问"第3章里他为什么走" | ❌ | `chat.py:28` 不挂任何工具，只在"有未落库草稿"时才看得到正文（§7.2） |
| 11 | 稿子摆在面前，先问一句再说 | ✅ | `confirm_chapter` 转 `chat` 答完回到那一问 |
| 12 | 说"这章不行，重写" | ✅ | `revise` 出口存在，旧稿作废 |
| 13 | 说"把张三改成反派" | ✅ | `plan → settle → impact → approve`，设计是对的 |
| 14 | 改完设定去翻受影响点 | ⚠️ | 看得到，`status / resolution` 也显示了，但 `method.py` **没有任何写口**，永远停在"未处理" |
| 15 | 说"在第2章后面插一章" | ❌ | `writer.save` 只会 `max(order)+1`（`writer.py:257`） |
| 16 | 同开两个标签页写同一本书 | ❌ | 流式期间 `_pending` 为假（`agent.py:316`），第二个 `/run` 会起第二轮图，快照互踩（§7.5） |
| 17 | 看这本书一共写了多少字 | ❌ | `/novels` 其实返回了 `wordCount`，但前端 `Novel` 类型只留 `{id,title,chapters}`（`types.ts:31`），没地方显示 |
| 18 | 想改这本书的类型 / 文风 | ❌ | `POST /novel` 只改书名；`EDIT_SPEC` 那八类里没有 `novel`（`impact.py:18`），对话也够不着（§7.13） |

**结论**：18 条主路里现在只有 3 条是干净的（11/12/13，正好都是 `editor`／`confirm_chapter` 那两条
子图 —— 说明"把控制流放进图"这个方向本身是对的）。其余 15 条的问题集中在两件事上：
"该落库的没落库"（第 6/7/8/9/14 条）与"草稿/任务没有身份"（第 2/3/4/15/16 条），
外加一笔独立的小账 —— **书本自身的属性没接上界面**（第 17/18 条，其中看的一半还是纯前端漏的）。
这正是 §3 那四条原则要解决的，也解释了为什么这次重构不推倒重来 —— 要动的是这两件事，不是图。

---

## 7. 缺口补齐设计（逐条对上 §6.5 里不平的路）

### 7.1 开书 → 开篇的交接

现状：`setup/save` 只写 `novel` 与设定，**不建第1章**；用户得回书架点开这本书再说一句"写第一章"。
设计：交接保持不变（开书图仍只存设定），但**在工作台给出显式入口**"写第一章"，
走主图 `write_next`（此时库里没有章，`order` 自然是 1）。
理由：把"建书"和"开篇"拆成两步是对的（用户可能在两件事之间去改设定），
缺的只是一个入口，不是后端逻辑。

### 7.2 `chat` 读不到已落库内容（高频且最容易被吐槽）

现状：`nodes/chat.py` 只 `chatModel.ainvoke`，**不挂任何工具**；只有在"本轮有未落库草稿"时
才把那一稿正文塞进上下文。于是"第3章里他为什么走"这类问题答不上来 —— 因为它读不到库里已存的正文。
设计：给 `chat` 挂上现成的 `tools/fetchDB.py`（已支持 15 张表的只读查询），
再补一张按 `chapterId` 直取正文的工具；把 `novel_chapter` 的检索字段从 `title/summary`
扩到 `content`。这样"问章节、问设定、对某点提疑问"全部有据可依。
**已拍板**：挂工具按需查，不做"每轮预取正文塞上下文"那套。

### 7.3 `extend` 的两个连带义务（否则静默损坏影响分析）

已在 3.3 写明，此处只做索引：**台账 merge 而非 DELETE 重写**（`ledger.DELETE_REFS` 是唯一底账）、
**正文变了必须重跑 `summarize`**（否则下一章写手读到过期前情）。

### 7.4 手动编辑与落库的并发

现状：`novel_chapter` 只有 `(novelId, order)` 唯一，正文整份 upsert，无版本。
设计：`apply_draft` 与手动保存都带 `baseUpdatedAt`；不一致返回 **409**，
前端提示"这章已被改动，请刷新"。这是主路上"AI 正在写、用户同时在改"的最小护栏。
**已拍板**：`409` 交给用户处理，不让 AI 或手改任何一方静默覆盖。

### 7.5 服务端单飞（多标签页 / 出错后重发）

现状有两层洞：

- **`/run` 的守卫只覆盖"停着等确认"那一段。** `_pending` 要求"正文非空 + 有问"
  （`agent.py:316`），而流式期间正文还只在模型消息里、没有 `active_chapter`，两个条件都不成立
  —— 于是**正在跑的这一轮，门口没有任何守卫**。
- **前端的单飞在网络错误时就松了。** `abortRef` 在 `finally` 里清（`useNovelAgent:229`），
  而此时服务端那一轮可能还在跑；用户再发一次，就在同一个 `thread_id` 上起了第二个图。

设计：`novel_task` 表上对 `(novelId, status IN (running, awaiting_user))` 建**唯一部分索引**，
`/run` 先插一行，撞索引就 409 并回当前 task。这既是 `/pending` 的稳定后端（不再依赖快照形状），
也顺手当了锁 —— 两个标签页只有一个能起。

### 7.6 设定面板只读，没有手工改设定的入口

现状：`SettingPanel/specs.ts` 的 `PANEL_SPECS` 只声明了展示字段，
用户想改一个设定只能走对话。
设计：保留"改设定优先走对话"（因为要连带影响分析），
但给面板加一个"在对话里改这个"的跳转按钮，把手工入口收敛到同一条更安全的路径上，
不新开一条绕过 `plan/settle/impact` 的写口。

### 7.7 章节标题的改名要落库

现状：`handleRenameChapter:443` 只改 React state（`ChapterList:144` 的 `EditableTitle` 调过去），
刷新即丢；而且库里 `novel_chapter.title` 是 writer 按"# 第N章 标题"写进去的，
用户改名之后两边还会再打架。
设计：补 `PATCH /chapter`（只动 `title` + `updatedAt`，与 `/chapter/status` 同款写法），
前端 `useChapter` 里加 `rename()`。**约定**：一旦用户手改过标题，就以库里的 `title` 为准，
writer 之后不再覆盖这一章的标题（`upsert_chapter` 时不带 title，或在 `novel_chapter_state`
上记一个"标题已手改"标记）。

### 7.8 灵感素材要真的送达 agent

现状：`AiPanel:74` 把附件交出，`handleSend:662` 只拿它渲染气泡，
真正发出去的 `run(activeNovelId, text, chapterId, handlers)`（`useNovelAgent:239`）里
**没有附件**。用户传的图 / 文件 / 链接，agent 一个都没见过。
设计：`/run` 请求体带上附件（文本类拼进提示词，图片走多模态）；
并把这批素材落进 `novel_inspiration`（表已经在了，`refType` 也在 `ledger.CATALOG` 里），
这样它才成为这本书的长期素材，而不是一条聊天气泡。

### 7.9 受影响点要有处理动作

现状：`novel_change_impact` 有 `status`(pending/accepted/skipped/fixed) 与 `resolution` 两列，
`ImpactsPanel:106` 也把 status 显示出来了 —— 但 `method.py` 里**没有对应的写口**，
这两个字段永远是初始值。用户看到"未处理"，却没有任何办法把它变成"已处理"。
设计：补 `POST /impact/status`（`{novelId, impactId, status, resolution?}`），
面板上给"接受 / 跳过 / 已修"三个动作。**不做**自动判定 —— 有没有影响由用户自己定。

### 7.10 停止生成

现状：`useNovelAgent` 内部有 `AbortController`，但**不对外暴露**；生成跑偏了只能刷新，
而刷新又会掉进 7.11 的坑。
设计：返回一个 `stop()`，前端在进度行旁边给"停止"按钮。
`stop()` 断流之后，后端那一轮要么跑完（走到 `confirm_chapter` 停下，稿还在，用户回来还能收），
要么被取消（见 7.11 的收尾语义）。两种都可以，关键是要**说得清**。

### 7.11 中途断开（刷新 / 断网）的行为要定义清楚

现状：SSE 一断，Starlette 的 `StreamingResponse` 会取消这一路生成器（它有一路专门听
`http.disconnect`），`astream` 随之中断 —— 半截正文连快照都没落；而 `/pending` 在流式期
又恒为假，前端也恢复不出任何东西。用户视角就是"我刷新一下，它刚写的全没了，也没报错"。
设计（三选一，P0 必须选一个）：

1. **明确的失败**：断开即把这一轮标成 cancelled（落在 `novel_task` 上），
   前端下次进来看到"上一轮中断了，重来 / 继续"；
2. **可恢复**：writer 每 N 步把已写正文落到 `novel_task.draft`，重连后从中断处续；
3. **后端跑完**：断开不取消图，让它跑到底停在 `confirm_chapter`，回来后 `/pending` 能捞回来。

建议 **1**（成本最低、语义最诚实）；等 7.5 的 `novel_task` 表在，1 几乎是白送的。

### 7.12 插章 / 删章的级联语义

现状：这两个动作后端都没有，所以"级联"根本没人管过。真做的时候要一并处理三处引用：

- `novel_chapter_ref`（台账，`chapterId` 外键，删章要级联）；
- `novel_change_impact`（`targetId` / `targetChapter` 指向章节）；
- **九类设定里的 `startChapterId / endChapterId` 生效区间** —— 删掉或插入一章之后，
  这些区间会指向已不存在的章，或者悄悄圈偏。这是"章号当身份"（§2 根因）的连带债，
  `store.py` 里做删章 / 插入时要放在**同一笔事务**里一起对齐。

### 7.13 小说自身的元信息：看不到，也改不了

现状分两半，两半的成因完全不同：

- **看，是白白没给。** `GET /novels` 其实早就把 `wordCount / tropes / style` 一起返回了
  （`method.py:184-186`），但前端 `Novel` 类型只声明了 `{id, title, chapters}`
  （`types.ts:31`），三个字段在**类型层**就被丢掉，UI 里更没有位置放。
  而 `novel.wordCount` 本身是准的 —— `upsert_chapter` 每章落库之后按
  `SUM(novel_chapter.wordCount)` 重算（`chapter_information.py:69`）。
  所以这不是"数据没有"，是"没给用户看"。
- **改，是根本没有入口。** `POST /novel` 只能改书名（`method.py:468`）；
  `tropes / style` 只在开书那一刻由 `save_novel_meta` 写一次
  （`novel_information.py:106`，写的是 `INSERT … ON CONFLICT (id) DO UPDATE` ——
  底子本来就能更新，只是建完书之后再没人调过）。对话那条路也够不着：
  `impact.EDIT_SPEC` 是从 `NEW_ENTITY_SPEC` 派生的八类设定（`impact.py:18`）外加 `outline`，
  **没有 `novel` 这一项**，所以"把文风改冷硬一点"这种话 editor 也接不住。

设计：

1. **看**：`Novel` 类型补上 `wordCount / tropes / style`，在侧栏或章节栏头部加一个"小说信息"区
   （共 N 字 · 类型 · 文风）。**纯前端改动，后端一个字不用动。**
2. **改**：`POST /novel` 扩成 `PATCH /novel`（`title / tropes / style` 三列，带 `updatedAt`），
   前端给就地编辑。**走显式表单，不经模型** —— 这是"书的属性"，跟改书名同类，
   没必要让 LLM 转一道手（§3.1 原则 3）。
3. **可选（放 P2）**：再把 `novel` 加进 `EDIT_SPEC`，让"把文风改得更冷硬些"这类话也能走对话。
   加它的真正理由是**影响分析**：改文风 / 类型会让**已经写完的那些章**风格对不上，
   这恰恰是"受影响点"该标出来的范围 —— 但这一条要动影响分析，先不做也不挡用户用。

---

## 8. 保留（现有设计里值得别动的部分）

- **控制流在图里、模型只做语义判断** —— 继续执行这条原则，本次重构是把它延伸到"目标解析"。
- **台账 `novel_chapter_ref` 反查影响面**：台账是影响分析的底账，别为省事砍掉。
- **标记常量单一来源**：`ledger.PROSE_MARK` / `MARK` / `TITLE_LINE` 三处（落库端、流式端、
  提示词）共用一份，`ProseFilter` 与 `split_submission` 同口径 —— 一定要保持。
- **流式筛子 `ProseFilter` / `SettingFilter`**：台账/JSON 不外泄的实现很干净。
- **开书图独立成 `novel_setup`**（独立 checkpointer 名）：与主图互不踩快照，是对的。
- **`/history` / `/pending` 这类"刷新重建现场"的只读口**：方向正确，本次只是把
  `/pending` 升级成 `/task` 并去掉启发式。

---

## 9. 文件索引

| 层 | 文件 | 关注点 |
|---|---|---|
| 图 | `agents/novel/__init__.py` | 主图装配与路由 |
| 图 | `agents/novel/setup/__init__.py` | 开书图 |
| 状态 | `agents/novel/state.py` | `active_chapter` 的拆分点 |
| 节点 | `nodes/intension.py` | → 拆为 `resolve` |
| 节点 | `nodes/writer.py` | `save` 的 `next_chapter_order` 是归属错位的源头 |
| 节点 | `nodes/editor.py` | `plan:348` 决定改哪一章；`approve` 的判词 |
| 节点 | `nodes/reader.py` | `chapter_id 为空` 约定 ×4 处之一 |
| 节点 | `nodes/confirm_chapter.py` | `_carried` 去重启发式 |
| 节点 | `nodes/update.py` | 唯一落库点 |
| 工具 | `utils/chapter_information.py` | `upsert_chapter` / `next_chapter_order`；`:69` 顺手重算 `novel.wordCount` |
| 工具 | `utils/novel_information.py` | `get_novel_meta` / `save_novel_meta`（`tropes/style` 只在开书写这一回） |
| 工具 | `utils/ledger.py` | 台账、标记常量、字段白名单 |
| 工具 | `utils/impact.py` | `EDIT_SPEC`、影响面启发式 |
| 入口 | `api/novel/agent.py` | SSE、`/pending`、`/history`、`/clear` |
| 入口 | `api/novel/method.py` | 三个写口；缺"保存正文/删章/改名/改类型文风" |
| 前端 | `home/novel/components/types.ts` | `:31` `Novel` 类型丢了 `wordCount/tropes/style` |
| 前端 | `home/novel/components/NovelWorkspace/index.tsx` | `:195` 归属、`:519/:499/:443` 三处不落库 |
| 前端 | `home/novel/components/ChapterBody/index.tsx` | `:96` 草稿顶替正文 |
| 前端 | `home/novel/components/useNovelAgent.ts` | SSE 解析；待加 `target`；`:239` 不带附件、无 `stop()` |
| 前端 | `home/novel/components/AiPanel/index.tsx` | `:76` 附件只用于渲染，发不出去 |
| 前端 | `home/novel/components/ImpactsPanel/index.tsx` | `:106` 显示 status，但没有写口 |
| 前端 | `home/novel/components/ChapterList/index.tsx` | `:144` 改名走 `handleRenameChapter`（不落库） |
| 数据 | `my-app/prisma/schema/novel.prisma` | schema 权威 |
