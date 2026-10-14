-- AlterTable: novel_inspiration 加使用策略 usage / 生命周期 lifecycle / 使用场景 scenario / 写作指引 digest。
-- 纯加列带默认值，不动已有数据：存量灵感策略一律"选用"、生命周期"复用"，场景与指引留空（重新翻译时补上）。
ALTER TABLE "novel_inspiration" ADD COLUMN "usage" TEXT NOT NULL DEFAULT 'selectable',
ADD COLUMN "lifecycle" TEXT NOT NULL DEFAULT 'reuse',
ADD COLUMN "scenario" TEXT NOT NULL DEFAULT '',
ADD COLUMN "digest" TEXT NOT NULL DEFAULT '';