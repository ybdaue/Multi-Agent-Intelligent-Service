-- Create ModelRoute table (replaces PricingConfig)
CREATE TABLE "ModelRoute" (
    "id" TEXT NOT NULL,
    "role" TEXT NOT NULL,
    "serviceType" TEXT NOT NULL,
    "provider" TEXT NOT NULL,
    "modelName" TEXT NOT NULL,
    "inputPrice" INTEGER NOT NULL,
    "outputPrice" INTEGER NOT NULL,
    "isActive" BOOLEAN NOT NULL DEFAULT true,
    "isBackup" BOOLEAN NOT NULL DEFAULT false,
    "priority" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMPTZ(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ(3) NOT NULL,
    CONSTRAINT "ModelRoute_pkey" PRIMARY KEY ("id")
);

-- Migrate existing data from PricingConfig (default role='pricing' for existing rows)
INSERT INTO "ModelRoute" ("id", "role", "serviceType", "provider", "modelName", "inputPrice", "outputPrice", "isActive", "isBackup", "priority", "createdAt", "updatedAt")
SELECT "id", 'pricing', "serviceType", "provider", "modelName", "inputPrice", "outputPrice", "isActive", "isBackup", "priority", "createdAt", "updatedAt"
FROM "PricingConfig";

-- Drop old PricingConfig table
DROP TABLE "PricingConfig";

-- Create indexes for ModelRoute
CREATE UNIQUE INDEX "ModelRoute_role_serviceType_provider_modelName_key" ON "ModelRoute"("role", "serviceType", "provider", "modelName");
CREATE INDEX "ModelRoute_serviceType_isActive_idx" ON "ModelRoute"("serviceType", "isActive");