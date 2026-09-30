-- Change ModelRoute.inputPrice/outputPrice from INTEGER (分/1K) to DOUBLE PRECISION (元/百万tokens)
ALTER TABLE "ModelRoute"
  ALTER COLUMN "inputPrice" TYPE double precision,
  ALTER COLUMN "outputPrice" TYPE double precision;

-- Convert existing values: 5分/1K → 50元/百万tokens (×10)
UPDATE "ModelRoute" SET
  "inputPrice" = "inputPrice" * 10,
  "outputPrice" = "outputPrice" * 10;