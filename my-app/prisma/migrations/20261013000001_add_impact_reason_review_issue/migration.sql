-- AlterEnum: ImpactReason 加 review_issue（章节审查问题，reader 审出的硬伤记进受影响点）
-- 追加枚举值，不动已有行；本迁移不使用该值，PG12+ 允许在同一事务里 ADD VALUE
ALTER TYPE "ImpactReason" ADD VALUE 'review_issue';