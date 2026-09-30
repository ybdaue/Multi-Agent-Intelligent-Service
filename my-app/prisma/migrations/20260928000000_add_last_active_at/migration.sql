-- 1. 新增 lastActiveAt 字段（当前冗余，方便快速查单用户最后活跃时间）
ALTER TABLE "User" ADD COLUMN "lastActiveAt" TIMESTAMPTZ(3);
UPDATE "User" SET "lastActiveAt" = "createdAt" WHERE "lastActiveAt" IS NULL;

-- 2. 新建用户活跃日志表，记录每日活跃用户，支持回溯历史 DAU
CREATE TABLE "UserActivityLog" (
    "id"        TEXT NOT NULL,
    "userId"    TEXT NOT NULL,
    "date"      DATE NOT NULL,
    "createdAt" TIMESTAMPTZ(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "UserActivityLog_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "UserActivityLog_userId_date_key" UNIQUE ("userId", "date")
);

-- 建立日期索引，趋势查询按 date 分组会用到
CREATE INDEX "UserActivityLog_date_idx" ON "UserActivityLog" ("date");

-- 将已有用户记录插入一条注册日期的活跃记录（默认注册即活跃）
INSERT INTO "UserActivityLog" ("id", "userId", "date")
SELECT gen_random_uuid()::text, "id", "createdAt"::date
FROM "User"
ON CONFLICT DO NOTHING;