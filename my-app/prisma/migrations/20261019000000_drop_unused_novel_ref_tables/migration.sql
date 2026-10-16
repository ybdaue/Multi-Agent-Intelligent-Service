-- 删除四张从未被写入的死表（均为 0 行，无数据可迁）：
--   novel_chapter_inspiration —— 已被书级 novel_inspiration 取代
--   novel_outline_ref / novel_timeline_ref / novel_chronicle_ref —— 关联改走 novel_chapter_ref
-- 手写而非 migrate diff：diff 会顺带带出本仓库活库与 schema 之间既存的计费表漂移，与本次无关。
-- DROP TABLE 会自动删掉这几张表自身的外键与索引；没有别的表指向它们，故无需先删约束。
DROP TABLE "novel_chapter_inspiration";
DROP TABLE "novel_outline_ref";
DROP TABLE "novel_timeline_ref";
DROP TABLE "novel_chronicle_ref";