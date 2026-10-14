export type ChapterStatus = "done" | "draft" | "fixing";

/** 状态的取值、下拉里的顺序、给用户看的字，三处一份，别各写各的 */
export const CHAPTER_STATUS_OPTIONS: { value: ChapterStatus; label: string }[] = [
  { value: "done", label: "完成" },
  { value: "draft", label: "草稿" },
  { value: "fixing", label: "待修复" },
];

export const CHAPTER_STATUS_LABEL: Record<ChapterStatus, string> = {
  done: "完成",
  draft: "草稿",
  fixing: "待修复",
};

/** 库里的那串字符认成一档；认不出的（老数据、后端新加的）按草稿算，不至于显示成空白 */
export function toChapterStatus(raw: string): ChapterStatus {
  return raw === "done" || raw === "fixing" ? raw : "draft";
}

export interface Chapter {
  id: string;
  title: string;
  /**
   * 库里的章序号（novel_chapter.order）。前端本地新建的临时章也按"当前最大序号 + 1"递补，
   * 所以它总能对上后端算出的 next_chapter_order。**认章认它** —— 标题里的"第N章"是给人看的，
   * 用户改过名就没了，拿它当身份会让同一个"第5章"被认成两个。
   */
  order?: number;
  /** done: 已定稿，只读展示；draft: 草稿，正文可编辑；fixing: 待修复，正文可编辑 */
  status: ChapterStatus;
  content: string;
  /** 这一章的字数（库里的 wordCount）；手改正文后由后端重算回填 */
  wordCount?: number;
  /**
   * 保存正文时带回去的版本令牌（库里的 updatedAt，微秒精度的原样字符串）。
   * **不透明**：不许进 new Date()、不许格式化 —— JS 的 Date 只有毫秒，尾数一掉就永远对不上。
   */
  version?: string;
  /** 前端刚建、库里的还没有这一行（占位章与 + 新建的章）：状态改不了，选择按钮也不给 */
  temp?: boolean;
}

/** 小说自己那几项元信息；类型与文风可在章节栏就地改，字数只读（后端按章节 SUM） */
export interface Novel {
  id: string;
  title: string;
  wordCount: number;
  tropes: string;
  style: string;
  /** AI 审稿开关：关掉后写/改完直接进确认，不走 reader */
  reviewEnabled: boolean;
  chapters: Chapter[];
}

/** 章节栏能就地改的两项（书名在侧栏改，不走这里） */
export type NovelMetaField = "tropes" | "style";

/** 正文区顶部导航条上挂着的那一轮生成：哪一章、还在写还是停下等答复 */
export interface RunChapter {
  id: string;
  title: string;
  pending: boolean;
}

export type MessageRole = "user" | "assistant";

/** 素材形态：图片/文件取 File，链接取 url，文本取输入的文字 */
export type InspirationKind = "image" | "file" | "url" | "text";

/** 灵感的内容类型（库里 novel_inspiration.category）。取值与后端 method.py 的 INSPIRATION_CATEGORIES 对齐。 */
export type InspirationCategory =
  | "style"
  | "plot"
  | "character"
  | "meme"
  | "setting"
  | "scene"
  | "dialogue"
  | "imagery"
  | "emotion"
  | "technique"
  | "other";

/** 取值、下拉里的顺序、给用户看的字，三处一份，别各写各的 */
export const INSPIRATION_CATEGORY_OPTIONS: { value: InspirationCategory; label: string }[] = [
  { value: "style", label: "风格" },
  { value: "plot", label: "剧情" },
  { value: "character", label: "人物" },
  { value: "meme", label: "热梗" },
  { value: "setting", label: "设定" },
  { value: "scene", label: "场景" },
  { value: "dialogue", label: "对话" },
  { value: "imagery", label: "意象" },
  { value: "emotion", label: "情感" },
  { value: "technique", label: "写作技巧" },
  { value: "other", label: "其他" },
];

export const INSPIRATION_CATEGORY_LABEL: Record<InspirationCategory, string> = {
  style: "风格",
  plot: "剧情",
  character: "人物",
  meme: "热梗",
  setting: "设定",
  scene: "场景",
  dialogue: "对话",
  imagery: "意象",
  emotion: "情感",
  technique: "写作技巧",
  other: "其他",
};

/** 使用策略（库里 novel_inspiration.usage）：必用每章带上，选用供挑选，不用直接排除。 */
export type InspirationUsage = "must" | "selectable" | "never";

export const INSPIRATION_USAGE_OPTIONS: { value: InspirationUsage; label: string }[] = [
  { value: "must", label: "必用" },
  { value: "selectable", label: "选用" },
  { value: "never", label: "不用" },
];

export const INSPIRATION_USAGE_LABEL: Record<InspirationUsage, string> = {
  must: "必用",
  selectable: "选用",
  never: "不用",
};

/** 生命周期（库里 novel_inspiration.lifecycle）：复用每章可再选，单次用过即退出候选。
 *  固定值、按分类自动定（剧情/人物/设定单次、其余复用），用户改不了，前端只读展示。 */
export type InspirationLifecycle = "reuse" | "once";

export const INSPIRATION_LIFECYCLE_LABEL: Record<InspirationLifecycle, string> = {
  reuse: "复用",
  once: "单次",
};

export interface InspirationItem {
  id: string;
  kind: InspirationKind;
  name: string;
  file?: File;
  /** 图片的预览地址，FileReader 读出的 data URL（不占 object URL 生命周期） */
  preview?: string;
  url?: string;
  /** 文本灵感的内容（kind === "text" 时用） */
  text?: string;
  size?: number;
  /** 对话里从灵感库挑中的那条的库内 id（普通上传件没有） */
  inspirationId?: string;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  attachments?: InspirationItem[];
  createdAt: number;
}

export type WorkTab =
  | "text"
  | "outline"
  | "characters"
  | "world"
  | "timeline"
  | "factions"
  | "chronicle"
  | "items"
  | "foreshadowing"
  | "relations"
  | "inspiration"
  | "export"
  /** 改动波及到哪些地方（novel_change_impact） */
  | "impacts";
