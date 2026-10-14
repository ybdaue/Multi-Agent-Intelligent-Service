import type { WorkTab } from "../types";

/** 一行设定：键就是库里的列名（后端照列名原样返回）。 */
export type Row = Record<string, unknown>;

export interface PanelField {
  key: string;
  label: string;
  /** 长文本：另起一行铺满，不跟别的字段挤在一起 */
  block?: boolean;
  /** 值怎么显示，默认照原样转字符串；空值一律不显示 */
  format?: (value: unknown, row: Row) => string;
}

export interface PanelSpec {
  /** 后端口子的路径（/api/novel/method/ 之后那一段，见 agents-project/api/novel/method.py） */
  endpoint: string;
  /** 返回体里那串数组的键 */
  listKey: string;
  /** 卡片标题取哪写哪 */
  title: (row: Row) => string;
  fields: PanelField[];
  /** 一条都没记时的提示 */
  empty: string;
}

const text = (value: unknown) => (value == null ? "" : String(value));

/** 正文里换行、空格都可能是随手敲的，标题只取一段干净的开头 */
function head(value: unknown, limit = 24) {
  const flat = text(value).replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit)}…` : flat;
}

/** 设定行上的 status 存的是枚举裸值，摆给用户看要翻成中文；认不出的原样给出去 */
const STATUS_LABELS: Record<string, string> = { draft: "草稿", done: "定稿" };
const status = (value: unknown) => STATUS_LABELS[text(value)] ?? text(value);

/** 大纲的分级裸值：主线 / 阶段线 / 支线（旧行没标 level 的一律是主线）。 */
const LINE_LEVEL_LABELS: Record<string, string> = { main: "主线", phase: "阶段线", branch: "支线" };
const lineLevel = (value: unknown) => LINE_LEVEL_LABELS[text(value)] ?? text(value);

/**
 * 各标签页的读法。键是 WorkTab，只列在库里真有表的那几个：
 * 正文走 /chapter/content（单独渲染），受影响点分组渲染，导出是前端自己拼的，都不在这张表里。
 */
export const PANEL_SPECS: Partial<Record<WorkTab, PanelSpec>> = {
  outline: {
    endpoint: "outlines",
    listKey: "outlines",
    title: (row) => head(row.content) || "大纲",
    fields: [
      { key: "level", label: "分级", format: lineLevel },
      { key: "status", label: "状态", format: status },
      { key: "content", label: "内容", block: true },
    ],
    empty: "这本书还没有大纲",
  },
  characters: {
    endpoint: "characters",
    listKey: "characters",
    title: (row) => {
      const name = text(row.name) || "未命名角色";
      return row.role ? `${name}（${text(row.role)}）` : name;
    },
    fields: [
      { key: "sex", label: "性别" },
      { key: "age", label: "年龄" },
      { key: "identity", label: "身份" },
      { key: "personality", label: "性格" },
      { key: "ability", label: "能力" },
      { key: "birthYear", label: "出生年份" },
      { key: "deathYear", label: "死亡年份" },
      { key: "description", label: "描述", block: true },
    ],
    empty: "这本书还没有人物",
  },
  world: {
    endpoint: "world-rules",
    listKey: "worldRules",
    title: (row) => text(row.name) || "未命名规则",
    fields: [
      { key: "status", label: "状态", format: status },
      { key: "rule", label: "规则内容", block: true },
    ],
    empty: "这本书还没有世界观设定",
  },
  timeline: {
    endpoint: "timelines",
    listKey: "timelines",
    title: (row) => text(row.title) || "未命名时间线",
    fields: [
      { key: "year", label: "年份" },
      { key: "status", label: "状态", format: status },
      { key: "description", label: "描述", block: true },
    ],
    empty: "这本书还没有世界线",
  },
  factions: {
    endpoint: "factions",
    listKey: "factions",
    title: (row) => text(row.name) || "未命名势力",
    fields: [
      { key: "type", label: "类型" },
      { key: "location", label: "所在地" },
      { key: "stance", label: "立场" },
      { key: "description", label: "描述", block: true },
    ],
    empty: "这本书还没有势力阵营",
  },
  chronicle: {
    endpoint: "chronicles",
    listKey: "chronicles",
    title: (row) => text(row.title) || "未命名事件",
    fields: [
      { key: "year", label: "年份" },
      { key: "content", label: "内容", block: true },
    ],
    empty: "这本书还没有编年史",
  },
  items: {
    endpoint: "items",
    listKey: "items",
    title: (row) => text(row.name) || "未命名物品",
    fields: [
      { key: "type", label: "类型" },
      { key: "status", label: "状态", format: status },
      { key: "ownerName", label: "持有者" },
      { key: "description", label: "描述", block: true },
    ],
    empty: "这本书还没有物品设定",
  },
  foreshadowing: {
    endpoint: "foreshadowings",
    listKey: "foreshadowings",
    title: (row) => head(row.description) || "伏笔",
    fields: [
      { key: "status", label: "状态", format: status },
      { key: "plantedChapter", label: "埋设章节" },
      { key: "resolvedChapter", label: "回收章节" },
      { key: "description", label: "描述", block: true },
    ],
    empty: "这本书还没有伏笔",
  },
  relations: {
    endpoint: "relations",
    listKey: "relations",
    title: (row) => `${text(row.fromName) || "？"} → ${text(row.toName) || "？"}`,
    fields: [
      { key: "relationType", label: "关系" },
      { key: "strength", label: "强度" },
      { key: "status", label: "状态", format: status },
      { key: "description", label: "描述", block: true },
    ],
    empty: "这本书还没有人物关系",
  },
};
