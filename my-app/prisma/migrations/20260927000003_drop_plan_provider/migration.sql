-- 删除 Plan 表多余的 provider 字段（套餐只按模型限制，不管供应商）
ALTER TABLE "Plan" DROP COLUMN provider;