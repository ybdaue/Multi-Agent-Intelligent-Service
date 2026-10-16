-- 灵感「用在哪些章」改由台账记：先把现有 usedChapterIds 逐条回填成 novel_chapter_ref，
-- 再删数组列。顺序不能反 —— 先删列历史关联就静默丢了。
INSERT INTO "novel_chapter_ref" (id, "chapterId", "refType", "refId", role, "createdAt")
SELECT md5(i.id || c.id), c.id, 'inspiration'::"RefType", i.id, 'key', now()
FROM "novel_inspiration" i
     CROSS JOIN LATERAL unnest(i."usedChapterIds") AS cid
     JOIN "novel_chapter" c ON c.id = cid
ON CONFLICT ("chapterId", "refType", "refId") DO NOTHING;

ALTER TABLE "novel_inspiration" DROP COLUMN "usedChapterIds";