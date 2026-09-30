-- 新增套餐系统表
-- 迁移: 20260927000002_add_plan_tables

-- 1. Plan 套餐商品目录
CREATE TABLE "Plan" (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    price INTEGER NOT NULL,
    description TEXT,
    "bonusAmount" INTEGER,
    "tokenAmount" INTEGER,
    "serviceType" TEXT,
    provider TEXT,
    "modelName" TEXT,
    "validityDays" INTEGER,
    "periodDays" INTEGER,
    "autoRenew" BOOLEAN DEFAULT true,
    "isActive" BOOLEAN DEFAULT true,
    "sortOrder" INTEGER DEFAULT 0,
    "createdAt" TIMESTAMPTZ(3) DEFAULT now(),
    "updatedAt" TIMESTAMPTZ(3) DEFAULT now()
);

-- 2. UserPlan 用户已购套餐实例
CREATE TABLE "UserPlan" (
    id TEXT PRIMARY KEY,
    "userId" TEXT NOT NULL REFERENCES "User"(id) ON DELETE CASCADE,
    "planId" TEXT NOT NULL REFERENCES "Plan"(id),
    status TEXT DEFAULT 'active',
    "purchasedAt" TIMESTAMPTZ(3) DEFAULT now(),
    "activatedAt" TIMESTAMPTZ(3),
    "expiresAt" TIMESTAMPTZ(3),
    "totalTokens" INTEGER NOT NULL,
    "usedTokens" INTEGER DEFAULT 0,
    "remainingTokens" INTEGER NOT NULL,
    "currentPeriodStart" TIMESTAMPTZ(3),
    "currentPeriodEnd" TIMESTAMPTZ(3),
    "lastRenewalAttempt" TIMESTAMPTZ(3)
);
CREATE INDEX "UserPlan_userId_status_remainingTokens_idx" ON "UserPlan"("userId", status, "remainingTokens");
CREATE INDEX "UserPlan_userId_status_expiresAt_idx" ON "UserPlan"("userId", status, "expiresAt");

-- 3. PlanTokenUsage 套餐 token 使用明细
CREATE TABLE "PlanTokenUsage" (
    id TEXT PRIMARY KEY,
    "userPlanId" TEXT NOT NULL REFERENCES "UserPlan"(id),
    "billingRecordId" TEXT NOT NULL REFERENCES "BillingRecord"(id),
    "modelName" TEXT NOT NULL,
    "inputTokens" INTEGER NOT NULL,
    "outputTokens" INTEGER NOT NULL,
    "deductedTokens" INTEGER NOT NULL,
    "createdAt" TIMESTAMPTZ(3) DEFAULT now()
);
CREATE INDEX "PlanTokenUsage_userPlanId_idx" ON "PlanTokenUsage"("userPlanId");

-- 4. BillingRecord 新增套餐抵扣字段
ALTER TABLE "BillingRecord" ADD COLUMN "planId" TEXT;
ALTER TABLE "BillingRecord" ADD COLUMN "planDeductedTokens" INTEGER;
ALTER TABLE "BillingRecord" ADD COLUMN "balanceDeductedCost" INTEGER;
CREATE INDEX "BillingRecord_planId_idx" ON "BillingRecord"("planId");

-- 5. RechargeRecord 新增套餐关联字段
ALTER TABLE "RechargeRecord" ADD COLUMN "planId" TEXT;