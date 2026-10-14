-- AlterTable: novel 加 reviewEnabled 列，控制是否开启 AI 审稿（reader 节点）
-- 纯加列、带默认值，不动已有数据：存量小说一律开启审查（true），保持原行为
ALTER TABLE "novel" ADD COLUMN "reviewEnabled" BOOLEAN NOT NULL DEFAULT true;