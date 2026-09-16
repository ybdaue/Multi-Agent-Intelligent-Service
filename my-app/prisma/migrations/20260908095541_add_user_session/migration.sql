-- AlterTable
ALTER TABLE "created_file" ALTER COLUMN "expiresAt" SET DEFAULT (now() + interval '7 days');

-- AlterTable
ALTER TABLE "temp_file" ALTER COLUMN "expiresAt" SET DEFAULT (now() + interval '7 days');

-- CreateTable
CREATE TABLE "user_session" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "agentName" TEXT NOT NULL,
    "threadId" TEXT NOT NULL,
    "title" TEXT NOT NULL DEFAULT '',
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "user_session_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "user_session_history" (
    "id" TEXT NOT NULL,
    "sessionId" TEXT NOT NULL,
    "messages" JSONB NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "user_session_history_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "user_session_userId_agentName_idx" ON "user_session"("userId", "agentName");

-- CreateIndex
CREATE UNIQUE INDEX "user_session_userId_agentName_threadId_key" ON "user_session"("userId", "agentName", "threadId");

-- CreateIndex
CREATE UNIQUE INDEX "user_session_history_sessionId_key" ON "user_session_history"("sessionId");

-- AddForeignKey
ALTER TABLE "user_session_history" ADD CONSTRAINT "user_session_history_sessionId_fkey" FOREIGN KEY ("sessionId") REFERENCES "user_session"("id") ON DELETE CASCADE ON UPDATE CASCADE;
