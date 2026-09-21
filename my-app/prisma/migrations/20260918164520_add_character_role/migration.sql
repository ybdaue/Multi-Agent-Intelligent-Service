-- AlterTable
ALTER TABLE "novel_character" ADD COLUMN     "role" TEXT NOT NULL DEFAULT '配角';

-- CreateIndex
CREATE INDEX "novel_character_novelId_role_idx" ON "novel_character"("novelId", "role");
