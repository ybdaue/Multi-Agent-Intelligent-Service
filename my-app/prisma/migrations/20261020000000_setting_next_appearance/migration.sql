-- 会随剧情演变的五类（人物 / 势力 / 物品 / 世界规则 / 关系）版本链改向：origin + change
-- → next + firstAppearanceChapterId。
--   旧口径：新行的 origin 指上一版、change 是这一版从哪一章起生效；链尾由「没有被谁的 origin
--           指向」反查得到，每条版本行本身不带"出现章节"。
--   新口径：旧行的 next 指向新行（无外键，自引用链），next IS NULL 即当前版（比反查少一次子查询）；
--           每条版本行自带的 firstAppearanceChapterId 就是"这一版出现在哪一章"，前端直接可显示。
-- 另：编年史（记录类、值不变）补一列 startChapterId，与大纲 / 时间线对齐。
-- 手写而非 migrate diff：diff 会顺带带出本仓库活库与 schema 之间既存的计费表漂移，与本次无关。
-- 每条都写成幂等（IF [NOT] EXISTS）：Prisma 不把整个迁移包在一个事务里，中途失败会留下"前几条
-- 已生效"的半成品；幂等写法让重跑能把剩下的补齐。**顺序不能反：先回填、再删列。**

-- 1. 加列
ALTER TABLE "novel_character"  ADD COLUMN IF NOT EXISTS "next" TEXT, ADD COLUMN IF NOT EXISTS "firstAppearanceChapterId" TEXT;
ALTER TABLE "novel_faction"    ADD COLUMN IF NOT EXISTS "next" TEXT, ADD COLUMN IF NOT EXISTS "firstAppearanceChapterId" TEXT;
ALTER TABLE "novel_world_rule" ADD COLUMN IF NOT EXISTS "next" TEXT, ADD COLUMN IF NOT EXISTS "firstAppearanceChapterId" TEXT;
ALTER TABLE "novel_relation"   ADD COLUMN IF NOT EXISTS "next" TEXT, ADD COLUMN IF NOT EXISTS "firstAppearanceChapterId" TEXT;
ALTER TABLE "novel_item"       ADD COLUMN IF NOT EXISTS "next" TEXT; -- firstAppearanceChapterId 本就有
ALTER TABLE "novel_chronicle"  ADD COLUMN IF NOT EXISTS "startChapterId" TEXT;

-- 2. 回填 next（由旧 origin 反推）：旧行 c 的 origin 指着本行 t.id，则本行 t 的 next 就是 c.id。
UPDATE "novel_character"  t SET "next" = c.id FROM "novel_character"  c WHERE c."origin" = t.id;
UPDATE "novel_faction"    t SET "next" = c.id FROM "novel_faction"    c WHERE c."origin" = t.id;
UPDATE "novel_world_rule" t SET "next" = c.id FROM "novel_world_rule" c WHERE c."origin" = t.id;
UPDATE "novel_relation"   t SET "next" = c.id FROM "novel_relation"   c WHERE c."origin" = t.id;
UPDATE "novel_item"       t SET "next" = c.id FROM "novel_item"       c WHERE c."origin" = t.id;

-- 3. 回填 firstAppearanceChapterId = change（item 保住已有的值，可能有行本就填过首次出现章）。
UPDATE "novel_character"  SET "firstAppearanceChapterId" = "change" WHERE "firstAppearanceChapterId" IS NULL;
UPDATE "novel_faction"    SET "firstAppearanceChapterId" = "change" WHERE "firstAppearanceChapterId" IS NULL;
UPDATE "novel_world_rule" SET "firstAppearanceChapterId" = "change" WHERE "firstAppearanceChapterId" IS NULL;
UPDATE "novel_relation"   SET "firstAppearanceChapterId" = "change" WHERE "firstAppearanceChapterId" IS NULL;
UPDATE "novel_item"       SET "firstAppearanceChapterId" = COALESCE("firstAppearanceChapterId", "change");

-- 4. 删旧列
ALTER TABLE "novel_character"  DROP COLUMN IF EXISTS "origin", DROP COLUMN IF EXISTS "change";
ALTER TABLE "novel_faction"    DROP COLUMN IF EXISTS "origin", DROP COLUMN IF EXISTS "change";
ALTER TABLE "novel_world_rule" DROP COLUMN IF EXISTS "origin", DROP COLUMN IF EXISTS "change";
ALTER TABLE "novel_relation"   DROP COLUMN IF EXISTS "origin", DROP COLUMN IF EXISTS "change";
ALTER TABLE "novel_item"       DROP COLUMN IF EXISTS "origin", DROP COLUMN IF EXISTS "change";

-- 5. 索引改向：链尾判定由反查 origin 变成 next IS NULL。
DROP INDEX IF EXISTS "novel_character_novelId_origin_idx";
DROP INDEX IF EXISTS "novel_faction_novelId_origin_idx";
DROP INDEX IF EXISTS "novel_item_novelId_origin_idx";
DROP INDEX IF EXISTS "novel_world_rule_novelId_origin_idx";
DROP INDEX IF EXISTS "novel_relation_novelId_origin_idx";

CREATE INDEX IF NOT EXISTS "novel_character_novelId_next_idx"  ON "novel_character"("novelId", "next");
CREATE INDEX IF NOT EXISTS "novel_faction_novelId_next_idx"    ON "novel_faction"("novelId", "next");
CREATE INDEX IF NOT EXISTS "novel_item_novelId_next_idx"       ON "novel_item"("novelId", "next");
CREATE INDEX IF NOT EXISTS "novel_world_rule_novelId_next_idx" ON "novel_world_rule"("novelId", "next");
CREATE INDEX IF NOT EXISTS "novel_relation_novelId_next_idx"   ON "novel_relation"("novelId", "next");