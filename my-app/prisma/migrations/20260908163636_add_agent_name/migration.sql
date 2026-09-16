-- AlterTable
ALTER TABLE "agent_store" ADD COLUMN "agentName" TEXT NOT NULL;

-- AlterTable
ALTER TABLE "checkpoint" ADD COLUMN "agentName" TEXT NOT NULL;

-- DropIndex
DROP INDEX "agent_store_userId_key_key";

-- DropIndex
DROP INDEX "checkpoint_userId_threadId_idx";

-- DropIndex
DROP INDEX "checkpoint_userId_threadId_checkpointId_key";

-- CreateIndex
CREATE UNIQUE INDEX "agent_store_userId_agentName_key_key" ON "agent_store"("userId", "agentName", "key");

-- CreateIndex
CREATE INDEX "checkpoint_userId_agentName_threadId_idx" ON "checkpoint"("userId", "agentName", "threadId");

-- CreateIndex
CREATE UNIQUE INDEX "checkpoint_userId_agentName_threadId_checkpointId_key" ON "checkpoint"("userId", "agentName", "threadId", "checkpointId");
