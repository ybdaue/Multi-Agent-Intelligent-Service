-- AlterTable: novel_outline 加 level 列，区分主线/阶段线/支线
-- 纯加列、带默认值，不动已有数据：旧大纲行一律归主线（main）
ALTER TABLE "novel_outline" ADD COLUMN "level" TEXT NOT NULL DEFAULT 'main';