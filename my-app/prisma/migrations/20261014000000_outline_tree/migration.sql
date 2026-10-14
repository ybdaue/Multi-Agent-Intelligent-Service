-- AlterTable: novel_outline 加自关联 parentId，表达「主线 ⊃ 阶段线 ⊃ 支线」的包含关系。
-- 阶段线挂主线、支线挂阶段线；主线自身 parentId 为空。旧行一并归 NULL（仍是各自为根）。
-- ON DELETE SET NULL（非 CASCADE）：重写某一章会撤掉「从这一章起头」的 phase/branch，级联删除
-- 会把后面章节挂在其名下的支线也带走 —— 那是后面的工作，不该被这一章的重写牵连。
ALTER TABLE "novel_outline" ADD COLUMN "parentId" TEXT;

ALTER TABLE "novel_outline" ADD CONSTRAINT "novel_outline_parentId_fkey"
  FOREIGN KEY ("parentId") REFERENCES "novel_outline"("id") ON DELETE SET NULL ON UPDATE CASCADE;

CREATE INDEX "novel_outline_novelId_parentId_idx" ON "novel_outline"("novelId", "parentId");