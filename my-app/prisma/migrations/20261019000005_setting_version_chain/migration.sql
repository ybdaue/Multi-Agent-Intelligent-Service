-- 会随剧情演变的五类（人物 / 势力 / 物品 / 世界规则 / 关系）改用版本行表达：
-- 每变一次新建一行，origin 指上一版那一行的 id（无外键，自引用链），change 是这一版从哪一章起
-- 生效（novel_chapter.id）。链尾（没有被谁的 origin 指向的那一行）就是"当前版"。
-- 手写而非 migrate diff：diff 会顺带带出本仓库活库与 schema 之间既存的计费表漂移，与本次无关。
-- 每条都写成幂等（IF [NOT] EXISTS）：Prisma 不把整个迁移包在一个事务里，中途失败会留下"前几条
-- 已生效"的半成品；幂等写法让重跑能把剩下的补齐。
ALTER TABLE "novel_character"  ADD COLUMN IF NOT EXISTS "origin" TEXT, ADD COLUMN IF NOT EXISTS "change" TEXT;
ALTER TABLE "novel_faction"    ADD COLUMN IF NOT EXISTS "origin" TEXT, ADD COLUMN IF NOT EXISTS "change" TEXT;
ALTER TABLE "novel_item"       ADD COLUMN IF NOT EXISTS "origin" TEXT, ADD COLUMN IF NOT EXISTS "change" TEXT;
ALTER TABLE "novel_world_rule" ADD COLUMN IF NOT EXISTS "origin" TEXT, ADD COLUMN IF NOT EXISTS "change" TEXT;
ALTER TABLE "novel_relation"   ADD COLUMN IF NOT EXISTS "origin" TEXT, ADD COLUMN IF NOT EXISTS "change" TEXT;

-- 回填：现存行都是各自设定的唯一一版 —— origin 留空；change 取它原来的"起始章"（人物/势力/物品
-- 本来没有起点列，change 留空）。
UPDATE "novel_world_rule" SET "change" = "startChapterId";
UPDATE "novel_relation"   SET "change" = "startChapterId";

-- 删唯一索引：版本链下同名多版是正常的，"同时只一版开着"改由写入代码守（查了再插）。
-- 这几条是 @@unique 落成的唯一**索引**（旧迁移里是 CREATE UNIQUE INDEX），不是表约束，故 DROP INDEX。
DROP INDEX IF EXISTS "novel_character_novelId_name_key";
DROP INDEX IF EXISTS "novel_faction_novelId_name_key";
DROP INDEX IF EXISTS "novel_item_novelId_name_key";
DROP INDEX IF EXISTS "novel_relation_novelId_fromCharId_toCharId_relationType_key";

-- world_rule / relation 的 start / end 退役（起点由第一版的 change 表达）；timeline 只删 end
-- （记录类、值不变，保留 start = 事件发生的章）。与章节的挂接一律走 novel_chapter_ref。
ALTER TABLE "novel_world_rule" DROP COLUMN IF EXISTS "startChapterId", DROP COLUMN IF EXISTS "endChapterId";
ALTER TABLE "novel_relation"   DROP COLUMN IF EXISTS "startChapterId", DROP COLUMN IF EXISTS "endChapterId";
ALTER TABLE "novel_timeline"   DROP COLUMN IF EXISTS "endChapterId";

-- 链尾反查（NOT EXISTS origin = 本行.id）走索引。
CREATE INDEX IF NOT EXISTS "novel_character_novelId_origin_idx"  ON "novel_character"("novelId", "origin");
CREATE INDEX IF NOT EXISTS "novel_faction_novelId_origin_idx"    ON "novel_faction"("novelId", "origin");
CREATE INDEX IF NOT EXISTS "novel_item_novelId_origin_idx"       ON "novel_item"("novelId", "origin");
CREATE INDEX IF NOT EXISTS "novel_world_rule_novelId_origin_idx" ON "novel_world_rule"("novelId", "origin");
CREATE INDEX IF NOT EXISTS "novel_relation_novelId_origin_idx"   ON "novel_relation"("novelId", "origin");