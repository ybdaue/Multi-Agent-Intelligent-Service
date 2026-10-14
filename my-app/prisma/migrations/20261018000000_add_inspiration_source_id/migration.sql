-- AlterTable: novel_inspiration 加素材分组 id sourceId。
-- 一次新增（一份素材）可能按用户选的多个标签各生成一条灵感，这些行共享同一个 sourceId，
-- 前端据此把它们并进同一张卡片。纯加列带默认值：存量行一律空串，前端按"空串就各自成组"处理。
ALTER TABLE "novel_inspiration" ADD COLUMN "sourceId" TEXT NOT NULL DEFAULT '';