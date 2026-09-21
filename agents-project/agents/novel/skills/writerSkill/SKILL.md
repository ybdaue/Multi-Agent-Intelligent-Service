---
name: writerSkill
description: "番茄爆款小说的逐章创作助手——设定已经确认好之后，按顺序一章一章写正文。每章 2200-2800 字，章末必留悬念钩子且类型轮换，情绪曲线按「压-小扬-压-爆」推进，开头前 50 字决定点击率，写后做格式化、字数校验、质量审查与记忆更新。含长线连续性工程（.learnings 记忆系统、卷级章节规划、断点续写恢复、Mermaid 情节图解、9 维逻辑审查）。用于：续写新章节、改写/优化已有章节、长篇追更、按番茄算法调整章节节奏。开书前的设定确认与大纲规划不在本技能范围内，去用 setupSkill。"
metadata:
  language: zh-CN
  platform: 番茄小说 (Fanqie Novels)
  source: 自 fanqie-crafter 拆出的「章节编写」部分
---

# 番茄章节创作 · Chapter Crafter

用于**设定已经定下来之后**的逐章创作：写新章、改已有章节、长篇追更。

开书前的六问、提示词完善、大纲规划、人物档案、情绪曲线与黄金开篇在 **setupSkill** 里，
本技能假定 `00-大纲.md`、`01-人物档案.md`、`02-情绪曲线.md`、`03-黄金开篇.md` 已经就绪。

## 何时使用

- 用户要写某一章、下一章，或续写/中断后接着写。
- 用户要改已有章节：重写、润色、扩写、缩写、调节奏。
- 用户要求章节更「番茄味」：开章抓人、情绪过山车、评论区能吵起来、完读率更高。
- 用户需要长线不穿帮：角色不串、伏笔能收、跨卷不断档。

## 何时不使用

- 还没确认设定、用户只有一句话方向 → 先用 **setupSkill** 把设定补齐。
- 单篇短文、文案、非连载故事 → 不必启用长篇工程。

## 项目结构与初始化

每本书一个目录（已存在则复用）：

```
novels/[小说名称]/
├── 00-大纲.md            # 作品基因 + 节奏蓝图 + 章节细纲 + 悬念线 + 进度看板 + 摘要
├── 01-人物档案.md         # 主角/反派/配角 + 关系张力图 + 评论区诱导设计
├── 02-情绪曲线.md         # 情绪单元规划 + 每章钩子/伏笔记录
├── 03-黄金开篇.md         # 开篇 50 字三版（强冲突/强反差/强情绪）
├── 第01章.md ...          # 各章节文件（2200-2800 字）
└── .learnings/           # 连续性记忆（见「记忆管理」）
    ├── CHARACTERS.md
    ├── LOCATIONS.md
    ├── PLOT_POINTS.md
    ├── STORY_BIBLE.md
    ├── ERRORS.md
    └── 审查记录.md
```

前四个文件由 setupSkill 产出；`.learnings/` 的五个文件模板见 `templates/memory-templates.md`，
首次使用按模板初始化空表头。

## 工作流总览

```
已有设定（00-大纲 / 01-人物档案 / 02-情绪曲线 / 03-黄金开篇）
        ↓
 ① 写前必读 → 写前分析（钩子 / 情绪定位 / 场景 / 章末钩子）
        ↓
 ② 撰写（2200-2800 字，展示而非讲述，去 AI 味）
        ↓
 ③ 写后处理（格式化 → 字数校验 → 质量审查 → 记忆更新 → 大纲同步）
        ↓  ┌─ 每 5 章：节奏报告 + 数据反馈循环 ─┐
 ④ 关键情节图解（Mermaid）+ 续写 / 中断恢复
```

**重要：按顺序逐章创作；每完成 5 章，生成节奏报告并询问用户数据反馈（完读率/追读率/评论关键词），据反馈调整后续大纲。**

## 阶段三：逐章创作

### 3.1 写前必读（每次生成新章前）

```
novels/[书名]/00-大纲.md        → 全局走向、节奏蓝图、本章在情绪单元中的位置
novels/[书名]/02-情绪曲线.md     → 本章情绪任务与已用钩子类型
.learnings/CHARACTERS.md        → 所有角色当前状态（等级/位置/生死）
.learnings/LOCATIONS.md         → 已出现地点
.learnings/PLOT_POINTS.md       → 已发生情节与待回收伏笔
.learnings/STORY_BIBLE.md       → 世界观设定与规则
novels/[书名]/第(最新)章.md      → 上一章内容，确保衔接
```

### 3.2 写前分析

1. **开头钩子设计**（最关键）：前 20% 必须有即时冲突/反常/危机，参考 `references/chapter-guide.md`
   （10 种开头技巧）与黄金开篇避雷针（在 setupSkill，见文末「跨技能参考」）。前 50 字决定书架页点击率。
2. **情绪曲线定位**：确认本章在「压-小扬-压-爆」单元中的任务（压/小扬/爆预告），单章内至少 3 次
   情绪变化（见 setupSkill 的 `references/emotion-curve.md`）。
3. **场景规划**：本章需 3-5 个场景，至少一个场景具备本情绪标签特征。
4. **章末钩子**：从 `references/hook-techniques.md`（10 种钩子）选类型，且与上一章**轮换**。

### 3.3 撰写

用 `templates/chapter-template.md` 生成章节。硬约束：

- **字数 2200-2800**（番茄最佳阅读长度）；低于 2200 用 `references/content-expansion.md` 扩充，
  高于 2800 精简。
- **展示而非讲述**：用动作/对话表现，删除「璀璨/瑰丽」类过度修饰、四字格律堆砌、抽象陈述。
- **去 AI 味**：避免「此外/然而/强调」等 AI 词汇；长短句交错；对话有角色个性与潜台词
  （见 `references/dialogue-writing.md`）。
- **每章必留钩子**，且钩子类型轮换；章末预留「评论区诱导留白」。

### 3.4 写后处理（每章必做）

| 步骤 | 操作 |
|------|------|
| 格式化 | `python scripts/format_chapter.py novels/[书名]/第XX章.md` |
| 字数校验 | `python scripts/check_chapter_wordcount.py novels/[书名]/第XX章.md`（须落在 2200-2800） |
| 质量审查 | 常规章：快速 3 维（见 `references/review-dimensions.md`）+ 工艺清单 `references/quality-checklist.md` 评分 **>60 才可交付**；卷末/问题章：完整 9 维审查 |
| 记忆更新 | 新角色→`CHARACTERS.md`、新地点→`LOCATIONS.md`、关键情节/伏笔→`PLOT_POINTS.md`、新设定→`STORY_BIBLE.md`、问题→`ERRORS.md` |
| 大纲同步 | 在 `00-大纲.md` 进度看板标记完成、追加 100-200 字章节摘要、在 `02-情绪曲线.md` 标注实际钩子类型 |

---

## 阶段四：关键情节图解

当出现关键战斗、势力地图、等级突破、人物关系、重大剧情线时，用 Mermaid 语法生成图解
（嵌入对应 md 或独立文件）。十大爽文套路与情绪曲线设计规范见 setupSkill 的
`references/plot-structures.md`。

## 阶段五：记忆管理（长线防穿帮）

每次写前必读 `.learnings/` 全部文件，确保：已死角色不复活、地点不矛盾、伏笔有回收、
等级不倒退、设定不自相矛盾。模板与更新规则见 `templates/memory-templates.md`。
审查发现穿帮时联动写入 `ERRORS.md` 并更正对应记忆文件。

## 阶段六：续写 / 中断恢复

长篇常中断，需从断点继续。续写前**按顺序**读取：00-大纲.md → 当前卷章节规划 →
CHARACTERS/LOCATIONS/PLOT_POINTS/STORY_BIBLE → 审查记录 → 最新章节。确认当前章号、
下一章核心任务、待回收伏笔、消失过久的配角，再按标准流程续写。

---

## 脚本

- **`scripts/check_chapter_wordcount.py <章节文件>`**（或 `--all <目录>`）：统计正文中文字数，
  报告是否落在 2200-2800 最佳区间；已处理 Windows 控制台编码。
- **`scripts/format_chapter.py <文件或目录>`**：清理章节文件中间多余 `---` 分隔符，仅保留首尾两个。

## 创作原则与禁忌

- **强代入感 + 快节奏**：每章有进展，不连续两章以上无爽点/无冲突。
- **情绪过山车**：每 3 章完成一次「压-小扬-压-爆」；章末钩子强度不低于上一章。
- **展示而非讲述、去 AI 味**：这是番茄读者留存的关键。
- **伏笔呼应**：前文埋的线后文要收；长期伏笔 >30 章未回收即预警。
- **反派不蠢**：衬托不出主角强；金手指有规则限制，不开无限制挂。

## 跨技能参考

这几份在 setupSkill 里，用技能工具按下面的路径读：

| 读法 | 用途 |
|------|------|
| `read_skill_file("setupSkill", "references/emotion-curve.md")` | 情绪曲线「压-小扬-压-爆」+ 评论区诱导 |
| `read_skill_file("setupSkill", "references/golden-opening.md")` | 黄金开篇 50 字锻造与避雷针 |
| `read_skill_file("setupSkill", "references/plot-structures.md")` | 爽文情节结构、十大套路、伏笔规范 |

## 参考文件索引

| 文件 | 用途 |
|------|------|
| `references/chapter-guide.md` | 10 种开头技巧、标准章节结构、节奏控制 |
| `references/hook-techniques.md` | 10 种章末悬念钩子与升级 |
| `references/dialogue-writing.md` | 对话目的/格式/声音区分/潜台词 |
| `references/content-expansion.md` | 字数不足时的自然扩充技巧 |
| `references/continuity.md` | 长线连贯性与穿帮检查清单 |
| `references/quality-checklist.md` | 8 维工艺质量清单（>60 可交付） |
| `references/review-dimensions.md` | 快速 3 维 + 完整 9 维逻辑审查模板 |
| `templates/chapter-template.md` | 单章生成模板（含平台字段与自检） |
| `templates/memory-templates.md` | `.learnings/` 五类记忆文件模板 |
