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
  /** done: 已定稿，只读展示；draft: 草稿，正文可编辑；fixing: 待修复，正文可编辑 */
  status: ChapterStatus;
  content: string;
  /** 前端刚建、库里的还没有这一行（占位章与 + 新建的章）：状态改不了，选择按钮也不给 */
  temp?: boolean;
}

export interface Novel {
  id: string;
  title: string;
  chapters: Chapter[];
}

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
