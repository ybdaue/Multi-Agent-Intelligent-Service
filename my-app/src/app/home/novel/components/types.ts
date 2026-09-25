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

/** 灵感素材：图片/文件取 File，链接取 url */
export type InspirationKind = "image" | "file" | "url";

export interface InspirationItem {
  id: string;
  kind: InspirationKind;
  name: string;
  file?: File;
  /** 图片的预览地址，FileReader 读出的 data URL（不占 object URL 生命周期） */
  preview?: string;
  url?: string;
  size?: number;
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
  | "relations"
  | "inspiration"
  | "export"
  /** 改动波及到哪些地方（novel_change_impact） */
  | "impacts";
