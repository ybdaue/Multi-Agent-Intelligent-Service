-- CreateTable
CREATE TABLE "temp_file" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "threadId" TEXT NOT NULL,
    "fileHash" TEXT NOT NULL,
    "originalName" TEXT NOT NULL,
    "mimeType" TEXT NOT NULL,
    "description" TEXT,
    "sizeBytes" INTEGER NOT NULL,
    "data" BYTEA NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "expiresAt" TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '7 days'),

    CONSTRAINT "temp_file_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "created_file" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "threadId" TEXT NOT NULL,
    "originalName" TEXT NOT NULL,
    "mimeType" TEXT NOT NULL,
    "description" TEXT,
    "sizeBytes" INTEGER NOT NULL,
    "data" BYTEA NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "expiresAt" TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '7 days'),

    CONSTRAINT "created_file_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "checkpoint" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "threadId" TEXT NOT NULL,
    "checkpointId" TEXT NOT NULL,
    "state" JSONB NOT NULL,
    "metadata" JSONB,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "checkpoint_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "agent_store" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "key" TEXT NOT NULL,
    "value" JSONB NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "agent_store_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "temp_file_expiresAt_idx" ON "temp_file"("expiresAt");

-- CreateIndex
CREATE UNIQUE INDEX "temp_file_userId_threadId_fileHash_key" ON "temp_file"("userId", "threadId", "fileHash");

-- CreateIndex
CREATE INDEX "created_file_userId_threadId_idx" ON "created_file"("userId", "threadId");

-- CreateIndex
CREATE INDEX "created_file_expiresAt_idx" ON "created_file"("expiresAt");

-- CreateIndex
CREATE INDEX "checkpoint_userId_threadId_idx" ON "checkpoint"("userId", "threadId");

-- CreateIndex
CREATE INDEX "checkpoint_userId_idx" ON "checkpoint"("userId");

-- CreateIndex
CREATE UNIQUE INDEX "checkpoint_userId_threadId_checkpointId_key" ON "checkpoint"("userId", "threadId", "checkpointId");

-- CreateIndex
CREATE INDEX "agent_store_userId_idx" ON "agent_store"("userId");

-- CreateIndex
CREATE UNIQUE INDEX "agent_store_userId_key_key" ON "agent_store"("userId", "key");
