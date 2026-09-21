-- CreateEnum
CREATE TYPE "ImpactTarget" AS ENUM ('novel', 'chapter', 'state', 'outline', 'timeline', 'chronicle', 'character', 'faction', 'item', 'relation', 'world_rule', 'foreshadowing');

-- CreateEnum
CREATE TYPE "ImpactReason" AS ENUM ('name_ref', 'stale_value', 'state_conflict', 'fk_dangling', 'order_shift', 'plot_conflict', 'outline_conflict', 'redundant');

-- CreateEnum
CREATE TYPE "ImpactSeverity" AS ENUM ('must_fix', 'review', 'info');

-- CreateEnum
CREATE TYPE "ImpactStatus" AS ENUM ('pending', 'accepted', 'skipped', 'fixed');

-- CreateTable
CREATE TABLE "novel_change_impact" (
    "id" TEXT NOT NULL,
    "novelId" TEXT NOT NULL,
    "changeId" TEXT NOT NULL,
    "changeSummary" TEXT NOT NULL,
    "sourceType" "ImpactTarget" NOT NULL,
    "sourceId" TEXT NOT NULL,
    "oldValue" TEXT,
    "newValue" TEXT,
    "targetType" "ImpactTarget" NOT NULL,
    "targetId" TEXT NOT NULL,
    "targetChapter" INTEGER,
    "reasonKind" "ImpactReason" NOT NULL,
    "reason" TEXT NOT NULL,
    "severity" "ImpactSeverity" NOT NULL DEFAULT 'review',
    "status" "ImpactStatus" NOT NULL DEFAULT 'pending',
    "resolution" TEXT,
    "detectedBy" TEXT NOT NULL DEFAULT '',
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "novel_change_impact_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "novel_change_impact_novelId_status_idx" ON "novel_change_impact"("novelId", "status");

-- CreateIndex
CREATE INDEX "novel_change_impact_novelId_targetType_targetId_idx" ON "novel_change_impact"("novelId", "targetType", "targetId");

-- CreateIndex
CREATE INDEX "novel_change_impact_changeId_idx" ON "novel_change_impact"("changeId");

-- CreateIndex
CREATE UNIQUE INDEX "novel_change_impact_changeId_targetType_targetId_reasonKind_key" ON "novel_change_impact"("changeId", "targetType", "targetId", "reasonKind");

-- CreateIndex
CREATE UNIQUE INDEX "novel_faction_novelId_name_key" ON "novel_faction"("novelId", "name");

-- CreateIndex
CREATE UNIQUE INDEX "novel_item_novelId_name_key" ON "novel_item"("novelId", "name");

-- CreateIndex
CREATE INDEX "novel_relation_novelId_fromCharId_idx" ON "novel_relation"("novelId", "fromCharId");

-- AddForeignKey
ALTER TABLE "novel_change_impact" ADD CONSTRAINT "novel_change_impact_novelId_fkey" FOREIGN KEY ("novelId") REFERENCES "novel"("id") ON DELETE CASCADE ON UPDATE CASCADE;
