-- Remove unused tables/models:
--   Post        - tutorial leftover, never used by app code
--   Verification- only needed for email-verification / reset-password, not enabled
--   User.password - legacy column; better-auth stores password hash in Account

DROP TABLE IF EXISTS "Post";
DROP TABLE IF EXISTS "Verification";
ALTER TABLE "User" DROP COLUMN IF EXISTS "password";
