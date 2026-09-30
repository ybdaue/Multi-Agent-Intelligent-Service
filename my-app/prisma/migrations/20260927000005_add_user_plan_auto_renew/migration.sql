-- UserPlan 新增 autoRenew 字段，默认继承 Plan 的 autoRenew 设置
ALTER TABLE "UserPlan" ADD COLUMN "autoRenew" BOOLEAN DEFAULT true;

-- 已有记录的 autoRenew 用其对应 Plan 的值
UPDATE "UserPlan" up
SET "autoRenew" = p."autoRenew"
FROM "Plan" p
WHERE up."planId" = p.id;