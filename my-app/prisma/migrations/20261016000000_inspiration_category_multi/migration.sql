-- AlterTable: novel_inspiration.category 由单值改为多值数组（一条灵感可同时属于多个内容类型）。
-- 存量单值就地包成单元素数组，不丢数据；默认值随之改为 ARRAY['other']。
ALTER TABLE "novel_inspiration" ALTER COLUMN "category" DROP DEFAULT;
ALTER TABLE "novel_inspiration" ALTER COLUMN "category" TYPE TEXT[] USING ARRAY["category"];
ALTER TABLE "novel_inspiration" ALTER COLUMN "category" SET DEFAULT ARRAY['other']::TEXT[];