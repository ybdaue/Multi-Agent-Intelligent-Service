-- CreateEnum
CREATE TYPE "RefType" AS ENUM ('character', 'faction', 'outline', 'timeline', 'chronicle', 'foreshadowing', 'item', 'inspiration', 'world_rule');

-- DropIndex
DROP INDEX "novel_chapter_novelId_order_idx";

-- AlterTable
ALTER TABLE "novel" DROP COLUMN "characters",
DROP COLUMN "chronicle",
DROP COLUMN "dialogueSummary",
DROP COLUMN "factions",
DROP COLUMN "foreshadowing",
DROP COLUMN "inspiration",
DROP COLUMN "items",
DROP COLUMN "outline",
DROP COLUMN "relations",
DROP COLUMN "timeline",
DROP COLUMN "world",
ALTER COLUMN "tropes" SET DATA TYPE TEXT USING "tropes"::text,
ALTER COLUMN "style" SET DATA TYPE TEXT USING "style"::text;

-- AlterTable
ALTER TABLE "novel_chapter" DROP COLUMN "inspiration",
DROP COLUMN "references";

-- CreateTable
CREATE TABLE "novel_chapter_state" (
    "id" TEXT NOT NULL,
    "chapterId" TEXT NOT NULL,
    "protagonistState" TEXT,
    "storyTime" TEXT,
    "eventProgress" TEXT,
    "worldState" TEXT,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "novel_chapter_state_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "novel_outline" (
    "id" TEXT NOT NULL,
    "novelId" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "startChapter" INTEGER,
    "endChapter" INTEGER,
    "order" INTEGER NOT NULL DEFAULT 0,
    "content" TEXT NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "novel_outline_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "novel_character" (
    "id" TEXT NOT NULL,
    "novelId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "sex" TEXT NOT NULL,
    "age" TEXT NOT NULL,
    "birthYear" TEXT NOT NULL,
    "deathYear" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "identity" TEXT NOT NULL,
    "personality" TEXT NOT NULL,
    "ability" TEXT NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "novel_character_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "novel_world_rule" (
    "id" TEXT NOT NULL,
    "novelId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "rule" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "startChapter" INTEGER,
    "endChapter" INTEGER,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "novel_world_rule_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "novel_timeline" (
    "id" TEXT NOT NULL,
    "novelId" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "year" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "startChapter" INTEGER,
    "endChapter" INTEGER,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "novel_timeline_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "novel_faction" (
    "id" TEXT NOT NULL,
    "novelId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "location" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "stance" TEXT NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "novel_faction_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "novel_chronicle" (
    "id" TEXT NOT NULL,
    "novelId" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "year" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "novel_chronicle_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "novel_item" (
    "id" TEXT NOT NULL,
    "novelId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "firstAppearance" INTEGER NOT NULL,
    "status" TEXT NOT NULL,
    "ownerId" TEXT,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "novel_item_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "novel_relation" (
    "id" TEXT NOT NULL,
    "novelId" TEXT NOT NULL,
    "fromCharId" TEXT NOT NULL,
    "toCharId" TEXT NOT NULL,
    "relationType" TEXT NOT NULL,
    "strength" INTEGER NOT NULL,
    "description" TEXT NOT NULL,
    "startChapter" INTEGER NOT NULL,
    "endChapter" INTEGER,
    "status" TEXT NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "novel_relation_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "novel_inspiration" (
    "id" TEXT NOT NULL,
    "novelId" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "usedChapter" INTEGER[],
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "novel_inspiration_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "novel_chapter_inspiration" (
    "id" TEXT NOT NULL,
    "chapterId" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "novel_chapter_inspiration_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "novel_foreshadowing" (
    "id" TEXT NOT NULL,
    "novelId" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "plantedChapter" INTEGER NOT NULL,
    "resolvedChapter" INTEGER,
    "status" TEXT NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "novel_foreshadowing_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "novel_chapter_ref" (
    "id" TEXT NOT NULL,
    "chapterId" TEXT NOT NULL,
    "refType" "RefType" NOT NULL,
    "refId" TEXT NOT NULL,
    "role" TEXT,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "novel_chapter_ref_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "novel_outline_ref" (
    "id" TEXT NOT NULL,
    "outlineId" TEXT NOT NULL,
    "refType" "RefType" NOT NULL,
    "refId" TEXT NOT NULL,
    "role" TEXT,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "novel_outline_ref_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "novel_timeline_ref" (
    "id" TEXT NOT NULL,
    "timelineId" TEXT NOT NULL,
    "refType" "RefType" NOT NULL,
    "refId" TEXT NOT NULL,
    "role" TEXT,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "novel_timeline_ref_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "novel_chronicle_ref" (
    "id" TEXT NOT NULL,
    "chronicleId" TEXT NOT NULL,
    "refType" "RefType" NOT NULL,
    "refId" TEXT NOT NULL,
    "role" TEXT,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "novel_chronicle_ref_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "novel_chapter_state_chapterId_key" ON "novel_chapter_state"("chapterId");

-- CreateIndex
CREATE INDEX "novel_outline_novelId_order_idx" ON "novel_outline"("novelId", "order");

-- CreateIndex
CREATE UNIQUE INDEX "novel_character_novelId_name_key" ON "novel_character"("novelId", "name");

-- CreateIndex
CREATE INDEX "novel_world_rule_novelId_idx" ON "novel_world_rule"("novelId");

-- CreateIndex
CREATE INDEX "novel_timeline_novelId_idx" ON "novel_timeline"("novelId");

-- CreateIndex
CREATE INDEX "novel_faction_novelId_idx" ON "novel_faction"("novelId");

-- CreateIndex
CREATE INDEX "novel_chronicle_novelId_idx" ON "novel_chronicle"("novelId");

-- CreateIndex
CREATE INDEX "novel_item_novelId_firstAppearance_idx" ON "novel_item"("novelId", "firstAppearance");

-- CreateIndex
CREATE INDEX "novel_item_ownerId_idx" ON "novel_item"("ownerId");

-- CreateIndex
CREATE INDEX "novel_relation_novelId_toCharId_idx" ON "novel_relation"("novelId", "toCharId");

-- CreateIndex
CREATE UNIQUE INDEX "novel_relation_novelId_fromCharId_toCharId_relationType_key" ON "novel_relation"("novelId", "fromCharId", "toCharId", "relationType");

-- CreateIndex
CREATE INDEX "novel_inspiration_novelId_idx" ON "novel_inspiration"("novelId");

-- CreateIndex
CREATE INDEX "novel_chapter_inspiration_chapterId_idx" ON "novel_chapter_inspiration"("chapterId");

-- CreateIndex
CREATE INDEX "novel_foreshadowing_novelId_plantedChapter_idx" ON "novel_foreshadowing"("novelId", "plantedChapter");

-- CreateIndex
CREATE INDEX "novel_foreshadowing_novelId_resolvedChapter_idx" ON "novel_foreshadowing"("novelId", "resolvedChapter");

-- CreateIndex
CREATE INDEX "novel_chapter_ref_refType_refId_idx" ON "novel_chapter_ref"("refType", "refId");

-- CreateIndex
CREATE UNIQUE INDEX "novel_chapter_ref_chapterId_refType_refId_key" ON "novel_chapter_ref"("chapterId", "refType", "refId");

-- CreateIndex
CREATE INDEX "novel_outline_ref_refType_refId_idx" ON "novel_outline_ref"("refType", "refId");

-- CreateIndex
CREATE UNIQUE INDEX "novel_outline_ref_outlineId_refType_refId_key" ON "novel_outline_ref"("outlineId", "refType", "refId");

-- CreateIndex
CREATE INDEX "novel_timeline_ref_refType_refId_idx" ON "novel_timeline_ref"("refType", "refId");

-- CreateIndex
CREATE UNIQUE INDEX "novel_timeline_ref_timelineId_refType_refId_key" ON "novel_timeline_ref"("timelineId", "refType", "refId");

-- CreateIndex
CREATE INDEX "novel_chronicle_ref_refType_refId_idx" ON "novel_chronicle_ref"("refType", "refId");

-- CreateIndex
CREATE UNIQUE INDEX "novel_chronicle_ref_chronicleId_refType_refId_key" ON "novel_chronicle_ref"("chronicleId", "refType", "refId");

-- CreateIndex
CREATE UNIQUE INDEX "novel_chapter_novelId_order_key" ON "novel_chapter"("novelId", "order");

-- AddForeignKey
ALTER TABLE "novel_chapter_state" ADD CONSTRAINT "novel_chapter_state_chapterId_fkey" FOREIGN KEY ("chapterId") REFERENCES "novel_chapter"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel_outline" ADD CONSTRAINT "novel_outline_novelId_fkey" FOREIGN KEY ("novelId") REFERENCES "novel"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel_character" ADD CONSTRAINT "novel_character_novelId_fkey" FOREIGN KEY ("novelId") REFERENCES "novel"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel_world_rule" ADD CONSTRAINT "novel_world_rule_novelId_fkey" FOREIGN KEY ("novelId") REFERENCES "novel"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel_timeline" ADD CONSTRAINT "novel_timeline_novelId_fkey" FOREIGN KEY ("novelId") REFERENCES "novel"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel_faction" ADD CONSTRAINT "novel_faction_novelId_fkey" FOREIGN KEY ("novelId") REFERENCES "novel"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel_chronicle" ADD CONSTRAINT "novel_chronicle_novelId_fkey" FOREIGN KEY ("novelId") REFERENCES "novel"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel_item" ADD CONSTRAINT "novel_item_novelId_fkey" FOREIGN KEY ("novelId") REFERENCES "novel"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel_item" ADD CONSTRAINT "novel_item_ownerId_fkey" FOREIGN KEY ("ownerId") REFERENCES "novel_character"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel_relation" ADD CONSTRAINT "novel_relation_novelId_fkey" FOREIGN KEY ("novelId") REFERENCES "novel"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel_inspiration" ADD CONSTRAINT "novel_inspiration_novelId_fkey" FOREIGN KEY ("novelId") REFERENCES "novel"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel_chapter_inspiration" ADD CONSTRAINT "novel_chapter_inspiration_chapterId_fkey" FOREIGN KEY ("chapterId") REFERENCES "novel_chapter"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel_foreshadowing" ADD CONSTRAINT "novel_foreshadowing_novelId_fkey" FOREIGN KEY ("novelId") REFERENCES "novel"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel_chapter_ref" ADD CONSTRAINT "novel_chapter_ref_chapterId_fkey" FOREIGN KEY ("chapterId") REFERENCES "novel_chapter"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel_outline_ref" ADD CONSTRAINT "novel_outline_ref_outlineId_fkey" FOREIGN KEY ("outlineId") REFERENCES "novel_outline"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel_timeline_ref" ADD CONSTRAINT "novel_timeline_ref_timelineId_fkey" FOREIGN KEY ("timelineId") REFERENCES "novel_timeline"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel_chronicle_ref" ADD CONSTRAINT "novel_chronicle_ref_chronicleId_fkey" FOREIGN KEY ("chronicleId") REFERENCES "novel_chronicle"("id") ON DELETE CASCADE ON UPDATE CASCADE;
