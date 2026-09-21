/*
  Warnings:

  - You are about to drop the column `keyPoints` on the `novel_chapter` table. All the data in the column will be lost.

*/
-- AlterTable
ALTER TABLE "novel_chapter" DROP COLUMN "keyPoints",
ADD COLUMN     "pastSummary" JSONB,
ADD COLUMN     "references" JSONB,
ADD COLUMN     "summary" TEXT;
