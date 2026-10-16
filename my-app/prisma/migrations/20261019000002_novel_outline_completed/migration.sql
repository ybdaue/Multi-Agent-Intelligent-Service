-- novel_outline 生命周期改显式：加 completed，删 endChapterId。
-- 旧的「有收尾章」即已完成；此后「收尾章是哪一章」由该章的 outline ref 记（novel_chapter_ref）。
ALTER TABLE "novel_outline" ADD COLUMN "completed" BOOLEAN NOT NULL DEFAULT false;

UPDATE "novel_outline" SET "completed" = ("endChapterId" IS NOT NULL)
 WHERE level IN ('phase', 'branch');

ALTER TABLE "novel_outline" DROP COLUMN "endChapterId";