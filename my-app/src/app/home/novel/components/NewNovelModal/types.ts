/** 设定项下的子字段状态（大分类下的小分类） */
export interface SubFieldStatus {
  key: string;
  label: string;
  required: boolean;
  collected: boolean;
  value: string;
}

/** GET /api/novel/setup/settings 返回的单字段状态 */
export interface SettingsFieldStatus {
  field: string;
  label: string;
  content: string;
  collected: boolean;
  sub_fields?: SubFieldStatus[];
}

/** GET /api/novel/setup/settings 返回体 */
export interface SettingsResponse {
  fields: SettingsFieldStatus[];
  dependencies: Record<string, string[]>;
}

/** 字段名到中文标签的 map（与后端 SETTING_LABELS 对齐） */
export const FIELD_LABELS: Record<string, string> = {
  novel_title: "书名",
  novel_tropes: "小说套路",
  novel_style: "小说风格",
  novel_protagonists: "主角",
  novel_outlines: "核心冲突",
  novel_world_rules: "世界观",
};