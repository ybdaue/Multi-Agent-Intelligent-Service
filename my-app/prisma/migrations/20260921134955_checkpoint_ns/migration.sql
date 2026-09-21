-- DropIndex
DROP INDEX "checkpoint_userId_agentName_threadId_checkpointId_key";

-- DropIndex
DROP INDEX "checkpoint_userId_agentName_threadId_idx";

-- AlterTable
ALTER TABLE "checkpoint" ADD COLUMN     "checkpointNs" TEXT NOT NULL DEFAULT '';

-- CreateIndex
CREATE INDEX "checkpoint_userId_agentName_threadId_checkpointNs_idx" ON "checkpoint"("userId", "agentName", "threadId", "checkpointNs");

-- CreateIndex
CREATE UNIQUE INDEX "checkpoint_userId_agentName_threadId_checkpointNs_checkpoin_key" ON "checkpoint"("userId", "agentName", "threadId", "checkpointNs", "checkpointId");
