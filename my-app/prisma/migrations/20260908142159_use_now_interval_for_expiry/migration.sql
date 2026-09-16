-- AlterTable
ALTER TABLE "created_file" ALTER COLUMN "expiresAt" SET DEFAULT (now() + interval '7 days');

-- AlterTable
ALTER TABLE "temp_file" ALTER COLUMN "expiresAt" SET DEFAULT (now() + interval '7 days');
