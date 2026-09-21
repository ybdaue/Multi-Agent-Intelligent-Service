-- CreateSchema
CREATE SCHEMA IF NOT EXISTS "public";

-- CreateTable
CREATE TABLE "User" (
    "id" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "emailVerified" BOOLEAN NOT NULL DEFAULT false,
    "name" TEXT,
    "image" TEXT,
    "createdAt" TIMESTAMPTZ(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ(3) NOT NULL,

    CONSTRAINT "User_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Session" (
    "id" TEXT NOT NULL,
    "expiresAt" TIMESTAMPTZ(3) NOT NULL,
    "token" TEXT NOT NULL,
    "createdAt" TIMESTAMPTZ(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ(3) NOT NULL,
    "ipAddress" TEXT,
    "userAgent" TEXT,
    "userId" TEXT NOT NULL,

    CONSTRAINT "Session_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Account" (
    "id" TEXT NOT NULL,
    "accountId" TEXT NOT NULL,
    "providerId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "accessToken" TEXT,
    "refreshToken" TEXT,
    "idToken" TEXT,
    "accessTokenExpiresAt" TIMESTAMPTZ(3),
    "refreshTokenExpiresAt" TIMESTAMPTZ(3),
    "scope" TEXT,
    "password" TEXT,
    "createdAt" TIMESTAMPTZ(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ(3) NOT NULL,

    CONSTRAINT "Account_pkey" PRIMARY KEY ("id")
);

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
    "expiresAt" TIMESTAMPTZ NOT NULL DEFAULT (now() + '7 days'::interval),

    CONSTRAINT "temp_file_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "legal_created_file" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "threadId" TEXT NOT NULL,
    "originalName" TEXT NOT NULL,
    "mimeType" TEXT NOT NULL,
    "description" TEXT,
    "sizeBytes" INTEGER NOT NULL,
    "data" BYTEA NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "expiresAt" TIMESTAMPTZ NOT NULL DEFAULT (now() + '7 days'::interval),

    CONSTRAINT "legal_created_file_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "legal_bm25" (
    "id" TEXT NOT NULL,
    "chunk_id" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "heading" TEXT,
    "file_id" TEXT NOT NULL,
    "chunk_index" INTEGER NOT NULL,
    "parent_index" INTEGER,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "legal_bm25_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "legal_laws" (
    "id" TEXT NOT NULL,
    "parent_id" TEXT NOT NULL,
    "file_id" TEXT NOT NULL,
    "parent_index" INTEGER NOT NULL,
    "heading" TEXT,
    "content" TEXT NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "legal_laws_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "checkpoint" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "agentName" TEXT NOT NULL,
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
    "agentName" TEXT NOT NULL,
    "key" TEXT NOT NULL,
    "value" JSONB NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "agent_store_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "user_session" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "agentName" TEXT NOT NULL,
    "threadId" TEXT NOT NULL,
    "title" TEXT NOT NULL DEFAULT '',
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "user_session_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "user_session_history" (
    "id" TEXT NOT NULL,
    "sessionId" TEXT NOT NULL,
    "agentName" TEXT NOT NULL,
    "messages" JSONB NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "user_session_history_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "novel" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "title" TEXT NOT NULL DEFAULT '',
    "wordCount" INTEGER NOT NULL DEFAULT 0,
    "outline" JSONB,
    "characters" JSONB,
    "world" JSONB,
    "timeline" JSONB,
    "factions" JSONB,
    "chronicle" JSONB,
    "items" JSONB,
    "relations" JSONB,
    "inspiration" JSONB,
    "dialogueSummary" JSONB,
    "foreshadowing" JSONB,
    "tropes" JSONB,
    "style" JSONB,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "novel_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "novel_chapter" (
    "id" TEXT NOT NULL,
    "novelId" TEXT NOT NULL,
    "title" TEXT NOT NULL DEFAULT '',
    "order" INTEGER NOT NULL DEFAULT 0,
    "status" TEXT NOT NULL DEFAULT 'draft',
    "content" TEXT NOT NULL DEFAULT '',
    "inspiration" JSONB,
    "keyPoints" JSONB,
    "wordCount" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "novel_chapter_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "User_email_key" ON "User"("email");

-- CreateIndex
CREATE UNIQUE INDEX "Session_token_key" ON "Session"("token");

-- CreateIndex
CREATE INDEX "Session_userId_idx" ON "Session"("userId");

-- CreateIndex
CREATE INDEX "Account_userId_idx" ON "Account"("userId");

-- CreateIndex
CREATE INDEX "temp_file_expiresAt_idx" ON "temp_file"("expiresAt");

-- CreateIndex
CREATE UNIQUE INDEX "temp_file_userId_threadId_fileHash_key" ON "temp_file"("userId", "threadId", "fileHash");

-- CreateIndex
CREATE INDEX "legal_created_file_userId_threadId_idx" ON "legal_created_file"("userId", "threadId");

-- CreateIndex
CREATE INDEX "legal_created_file_expiresAt_idx" ON "legal_created_file"("expiresAt");

-- CreateIndex
CREATE UNIQUE INDEX "legal_bm25_chunk_id_key" ON "legal_bm25"("chunk_id");

-- CreateIndex
CREATE INDEX "legal_bm25_file_id_idx" ON "legal_bm25"("file_id");

-- CreateIndex
CREATE UNIQUE INDEX "legal_laws_parent_id_key" ON "legal_laws"("parent_id");

-- CreateIndex
CREATE INDEX "legal_laws_file_id_parent_index_idx" ON "legal_laws"("file_id", "parent_index");

-- CreateIndex
CREATE INDEX "checkpoint_userId_agentName_threadId_idx" ON "checkpoint"("userId", "agentName", "threadId");

-- CreateIndex
CREATE INDEX "checkpoint_userId_idx" ON "checkpoint"("userId");

-- CreateIndex
CREATE UNIQUE INDEX "checkpoint_userId_agentName_threadId_checkpointId_key" ON "checkpoint"("userId", "agentName", "threadId", "checkpointId");

-- CreateIndex
CREATE INDEX "agent_store_userId_idx" ON "agent_store"("userId");

-- CreateIndex
CREATE UNIQUE INDEX "agent_store_userId_agentName_key_key" ON "agent_store"("userId", "agentName", "key");

-- CreateIndex
CREATE INDEX "user_session_userId_agentName_idx" ON "user_session"("userId", "agentName");

-- CreateIndex
CREATE UNIQUE INDEX "user_session_userId_agentName_threadId_key" ON "user_session"("userId", "agentName", "threadId");

-- CreateIndex
CREATE UNIQUE INDEX "user_session_history_sessionId_key" ON "user_session_history"("sessionId");

-- CreateIndex
CREATE INDEX "novel_userId_idx" ON "novel"("userId");

-- CreateIndex
CREATE INDEX "novel_chapter_novelId_order_idx" ON "novel_chapter"("novelId", "order");

-- AddForeignKey
ALTER TABLE "Session" ADD CONSTRAINT "Session_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Account" ADD CONSTRAINT "Account_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "checkpoint" ADD CONSTRAINT "checkpoint_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "agent_store" ADD CONSTRAINT "agent_store_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "user_session" ADD CONSTRAINT "user_session_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "user_session_history" ADD CONSTRAINT "user_session_history_sessionId_fkey" FOREIGN KEY ("sessionId") REFERENCES "user_session"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel" ADD CONSTRAINT "novel_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "novel_chapter" ADD CONSTRAINT "novel_chapter_novelId_fkey" FOREIGN KEY ("novelId") REFERENCES "novel"("id") ON DELETE CASCADE ON UPDATE CASCADE;
