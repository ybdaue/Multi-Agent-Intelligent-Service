-- 伏笔补一条「收尾」闭环：
--   status 语义改成生命周期两值 —— open 未收尾 / resolved 已收尾（旧值 draft 一律回填成 open，
--     因为此前根本没有"收尾"这条写入路径，现存的行都是没收回的）；
--   新增 resolveScenario：这个伏笔打算在什么场景下收尾，写手埋它的时候一并填，planner 照它判
--     本章该不该收。
-- 手写而非 migrate diff：diff 会顺带带出本仓库活库与 schema 之间既存的计费表漂移，与本次无关。
-- 写成幂等（IF [NOT] EXISTS / 有条件 UPDATE）：Prisma 不把整个迁移包在一个事务里，中途失败会留下
-- "前几条已生效"的半成品，幂等写法让重跑能把剩下的补齐。
ALTER TABLE "novel_foreshadowing"
  ADD COLUMN IF NOT EXISTS "resolveScenario" TEXT NOT NULL DEFAULT '';

ALTER TABLE "novel_foreshadowing" ALTER COLUMN "status" SET DEFAULT 'open';
UPDATE "novel_foreshadowing" SET "status" = 'open' WHERE "status" IS DISTINCT FROM 'resolved';

-- 未收尾伏笔要按 (novelId, status) 批量取（planner 必读），给它一条索引。
CREATE INDEX IF NOT EXISTS "novel_foreshadowing_novelId_status_idx"
  ON "novel_foreshadowing"("novelId", "status");