-- Convert all timestamp columns to timestamptz.
-- Existing values were written by Prisma as UTC into `timestamp without time zone`,
-- so reinterpret them as UTC when casting to preserve the correct instant.

-- User
ALTER TABLE "User" ALTER COLUMN "createdAt" SET DATA TYPE TIMESTAMPTZ(3) USING "createdAt" AT TIME ZONE 'UTC';
ALTER TABLE "User" ALTER COLUMN "updatedAt" SET DATA TYPE TIMESTAMPTZ(3) USING "updatedAt" AT TIME ZONE 'UTC';

-- Session
ALTER TABLE "Session" ALTER COLUMN "expiresAt" SET DATA TYPE TIMESTAMPTZ(3) USING "expiresAt" AT TIME ZONE 'UTC';
ALTER TABLE "Session" ALTER COLUMN "createdAt" SET DATA TYPE TIMESTAMPTZ(3) USING "createdAt" AT TIME ZONE 'UTC';
ALTER TABLE "Session" ALTER COLUMN "updatedAt" SET DATA TYPE TIMESTAMPTZ(3) USING "updatedAt" AT TIME ZONE 'UTC';

-- Account
ALTER TABLE "Account" ALTER COLUMN "accessTokenExpiresAt" SET DATA TYPE TIMESTAMPTZ(3) USING "accessTokenExpiresAt" AT TIME ZONE 'UTC';
ALTER TABLE "Account" ALTER COLUMN "refreshTokenExpiresAt" SET DATA TYPE TIMESTAMPTZ(3) USING "refreshTokenExpiresAt" AT TIME ZONE 'UTC';
ALTER TABLE "Account" ALTER COLUMN "createdAt" SET DATA TYPE TIMESTAMPTZ(3) USING "createdAt" AT TIME ZONE 'UTC';
ALTER TABLE "Account" ALTER COLUMN "updatedAt" SET DATA TYPE TIMESTAMPTZ(3) USING "updatedAt" AT TIME ZONE 'UTC';
