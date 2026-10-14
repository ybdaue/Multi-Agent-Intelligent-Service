-- AlterTable: novel_inspiration 加内容类型 category 与显示名 title，供灵感库分类/搜索/展示
-- 纯加列、带默认值，不动已有数据：存量灵感一律归为"其他"，显示名留空（前端按 content 兜底）
ALTER TABLE "novel_inspiration" ADD COLUMN "category" TEXT NOT NULL DEFAULT 'other',
ADD COLUMN "title" TEXT NOT NULL DEFAULT '';