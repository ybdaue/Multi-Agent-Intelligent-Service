-- AlterTable: Session 表加 revokedReason 和 revokedAt
-- 用于记录 session 被撤销的原因（被踢/封禁），保留数据不硬删
ALTER TABLE "Session" ADD COLUMN     "revokedAt" TIMESTAMPTZ(3),
ADD COLUMN     "revokedReason" TEXT;