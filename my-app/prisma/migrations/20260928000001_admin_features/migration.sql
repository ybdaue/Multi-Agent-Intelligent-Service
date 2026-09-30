-- Admin 后台补全功能：新增字段与表

-- 1. PricingConfig 加备用模型字段
ALTER TABLE "PricingConfig" ADD COLUMN IF NOT EXISTS "isBackup" BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE "PricingConfig" ADD COLUMN IF NOT EXISTS "priority" INTEGER NOT NULL DEFAULT 0;

-- 2. novel 加封禁字段
ALTER TABLE "novel" ADD COLUMN IF NOT EXISTS "banned" BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE "novel" ADD COLUMN IF NOT EXISTS "banReason" TEXT;
ALTER TABLE "novel" ADD COLUMN IF NOT EXISTS "bannedAt" TIMESTAMPTZ(3);

-- 3. novel_chapter 加封禁字段
ALTER TABLE "novel_chapter" ADD COLUMN IF NOT EXISTS "banned" BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE "novel_chapter" ADD COLUMN IF NOT EXISTS "banReason" TEXT;
ALTER TABLE "novel_chapter" ADD COLUMN IF NOT EXISTS "bannedAt" TIMESTAMPTZ(3);

-- 4. 创建系统公告表
CREATE TABLE IF NOT EXISTS "Announcement" (
    "id" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'draft',
    "priority" TEXT NOT NULL DEFAULT 'normal',
    "targetRole" TEXT,
    "publishAt" TIMESTAMPTZ(3),
    "expiresAt" TIMESTAMPTZ(3),
    "publishedAt" TIMESTAMPTZ(3),
    "createdBy" TEXT NOT NULL,
    "createdAt" TIMESTAMPTZ(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ(3) NOT NULL,
    CONSTRAINT "Announcement_pkey" PRIMARY KEY ("id")
);
CREATE INDEX IF NOT EXISTS "Announcement_status_publishAt_idx" ON "Announcement"("status", "publishAt");
CREATE INDEX IF NOT EXISTS "Announcement_status_expiresAt_idx" ON "Announcement"("status", "expiresAt");

-- 5. 创建管理员审计日志表
CREATE TABLE IF NOT EXISTS "AdminAuditLog" (
    "id" TEXT NOT NULL,
    "adminId" TEXT NOT NULL,
    "adminEmail" TEXT NOT NULL,
    "action" TEXT NOT NULL,
    "targetType" TEXT NOT NULL,
    "targetId" TEXT,
    "detail" TEXT,
    "metadata" JSONB,
    "createdAt" TIMESTAMPTZ(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "AdminAuditLog_pkey" PRIMARY KEY ("id")
);
CREATE INDEX IF NOT EXISTS "AdminAuditLog_adminId_createdAt_idx" ON "AdminAuditLog"("adminId", "createdAt");
CREATE INDEX IF NOT EXISTS "AdminAuditLog_targetType_targetId_idx" ON "AdminAuditLog"("targetType", "targetId");
CREATE INDEX IF NOT EXISTS "AdminAuditLog_createdAt_idx" ON "AdminAuditLog"("createdAt");

-- 6. Announcement 外键
ALTER TABLE "Announcement" ADD CONSTRAINT "Announcement_createdBy_fkey" FOREIGN KEY ("createdBy") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;