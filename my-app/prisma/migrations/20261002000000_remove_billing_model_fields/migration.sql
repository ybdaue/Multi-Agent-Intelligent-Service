-- Drop model-level columns from BillingRecord
ALTER TABLE "BillingRecord" DROP COLUMN "provider";
ALTER TABLE "BillingRecord" DROP COLUMN "modelName";
ALTER TABLE "BillingRecord" DROP COLUMN "inputCost";
ALTER TABLE "BillingRecord" DROP COLUMN "outputCost";
