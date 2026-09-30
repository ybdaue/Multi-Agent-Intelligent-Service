-- Drop old unique index
DROP INDEX IF EXISTS "ModelRoute_role_serviceType_provider_modelName_key";

-- Create new unique index including isBackup, so primary and backup
-- can use the same provider+modelName without conflict.
CREATE UNIQUE INDEX "ModelRoute_role_serviceType_provider_modelName_isBackup_key"
ON "ModelRoute"("role", "serviceType", "provider", "modelName", "isBackup");