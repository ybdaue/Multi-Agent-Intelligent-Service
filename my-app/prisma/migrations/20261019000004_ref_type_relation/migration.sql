-- 关系进台账：RefType 加 relation，novel_chapter_ref.refId 才能指向 novel_relation。
-- 单独一个迁移文件：PG 允许在事务里 ADD VALUE，但同一事务内不能再用这个新值，
-- 所以就这一条、不跟「用它的语句」同批。
ALTER TYPE "RefType" ADD VALUE IF NOT EXISTS 'relation';