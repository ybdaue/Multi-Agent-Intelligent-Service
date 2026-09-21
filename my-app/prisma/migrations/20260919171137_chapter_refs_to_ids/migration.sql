-- 把「裸章节号」(Int) 换成指向 novel_chapter.id 的字符串。
--
-- 不能只跑 prisma migrate diff 生成的那份：它只会 DROP 旧列 + ADD 新列，现有值全丢。
-- 这里对每张表都补一段回填 —— 按 (novelId, order) 把旧的章节号映射成 chapter id。
-- 找不到对应章的（含旧值为 NULL 的）就留 NULL。
--
-- 故意不声明 @relation：删章后留悬空 id，影响检测才看得见「这里引用了一个已删的章」。
-- 声明成 onDelete: SetNull 反而会把这类信息静默抹掉。

-- novel_item.firstAppearance -> firstAppearanceChapterId
ALTER TABLE "novel_item" ADD COLUMN "firstAppearanceChapterId" TEXT;
UPDATE "novel_item" i SET "firstAppearanceChapterId" = c."id"
  FROM "novel_chapter" c
  WHERE c."novelId" = i."novelId" AND c."order" = i."firstAppearance";
ALTER TABLE "novel_item" DROP COLUMN "firstAppearance";
CREATE INDEX "novel_item_novelId_firstAppearanceChapterId_idx" ON "novel_item"("novelId", "firstAppearanceChapterId");

-- novel_foreshadowing.plantedChapter / resolvedChapter -> plantedChapterId / resolvedChapterId
ALTER TABLE "novel_foreshadowing" ADD COLUMN "plantedChapterId" TEXT, ADD COLUMN "resolvedChapterId" TEXT;
UPDATE "novel_foreshadowing" f SET "plantedChapterId" = c."id"
  FROM "novel_chapter" c
  WHERE c."novelId" = f."novelId" AND c."order" = f."plantedChapter";
UPDATE "novel_foreshadowing" f SET "resolvedChapterId" = c."id"
  FROM "novel_chapter" c
  WHERE c."novelId" = f."novelId" AND c."order" = f."resolvedChapter";
ALTER TABLE "novel_foreshadowing" DROP COLUMN "plantedChapter", DROP COLUMN "resolvedChapter";
CREATE INDEX "novel_foreshadowing_novelId_plantedChapterId_idx" ON "novel_foreshadowing"("novelId", "plantedChapterId");
CREATE INDEX "novel_foreshadowing_novelId_resolvedChapterId_idx" ON "novel_foreshadowing"("novelId", "resolvedChapterId");

-- novel_inspiration.usedChapter[] -> usedChapterIds[]
-- 数组得逐项映射：unnest 摊平后按 order 找 id，再 array_agg 收回去；找不到的项丢掉。
ALTER TABLE "novel_inspiration" ADD COLUMN "usedChapterIds" TEXT[];
UPDATE "novel_inspiration" i SET "usedChapterIds" = COALESCE(
  (SELECT array_agg(c."id")
   FROM unnest(i."usedChapter") AS n(chapter_order)
   JOIN "novel_chapter" c ON c."novelId" = i."novelId" AND c."order" = n.chapter_order),
  ARRAY[]::TEXT[]
);
ALTER TABLE "novel_inspiration" DROP COLUMN "usedChapter";

-- novel_outline.startChapter / endChapter -> startChapterId / endChapterId
ALTER TABLE "novel_outline" ADD COLUMN "startChapterId" TEXT, ADD COLUMN "endChapterId" TEXT;
UPDATE "novel_outline" o SET "startChapterId" = c."id"
  FROM "novel_chapter" c
  WHERE c."novelId" = o."novelId" AND c."order" = o."startChapter";
UPDATE "novel_outline" o SET "endChapterId" = c."id"
  FROM "novel_chapter" c
  WHERE c."novelId" = o."novelId" AND c."order" = o."endChapter";
ALTER TABLE "novel_outline" DROP COLUMN "startChapter", DROP COLUMN "endChapter";

-- novel_world_rule.startChapter / endChapter -> startChapterId / endChapterId
ALTER TABLE "novel_world_rule" ADD COLUMN "startChapterId" TEXT, ADD COLUMN "endChapterId" TEXT;
UPDATE "novel_world_rule" w SET "startChapterId" = c."id"
  FROM "novel_chapter" c
  WHERE c."novelId" = w."novelId" AND c."order" = w."startChapter";
UPDATE "novel_world_rule" w SET "endChapterId" = c."id"
  FROM "novel_chapter" c
  WHERE c."novelId" = w."novelId" AND c."order" = w."endChapter";
ALTER TABLE "novel_world_rule" DROP COLUMN "startChapter", DROP COLUMN "endChapter";

-- novel_timeline.startChapter / endChapter -> startChapterId / endChapterId
ALTER TABLE "novel_timeline" ADD COLUMN "startChapterId" TEXT, ADD COLUMN "endChapterId" TEXT;
UPDATE "novel_timeline" t SET "startChapterId" = c."id"
  FROM "novel_chapter" c
  WHERE c."novelId" = t."novelId" AND c."order" = t."startChapter";
UPDATE "novel_timeline" t SET "endChapterId" = c."id"
  FROM "novel_chapter" c
  WHERE c."novelId" = t."novelId" AND c."order" = t."endChapter";
ALTER TABLE "novel_timeline" DROP COLUMN "startChapter", DROP COLUMN "endChapter";

-- novel_relation.startChapter / endChapter -> startChapterId / endChapterId
ALTER TABLE "novel_relation" ADD COLUMN "startChapterId" TEXT, ADD COLUMN "endChapterId" TEXT;
UPDATE "novel_relation" r SET "startChapterId" = c."id"
  FROM "novel_chapter" c
  WHERE c."novelId" = r."novelId" AND c."order" = r."startChapter";
UPDATE "novel_relation" r SET "endChapterId" = c."id"
  FROM "novel_chapter" c
  WHERE c."novelId" = r."novelId" AND c."order" = r."endChapter";
ALTER TABLE "novel_relation" DROP COLUMN "startChapter", DROP COLUMN "endChapter";
