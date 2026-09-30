-- 支付订单表
CREATE TABLE "PaymentOrder" (
    id TEXT PRIMARY KEY,
    "userId" TEXT NOT NULL REFERENCES "User"(id) ON DELETE CASCADE,
    "planId" TEXT,
    amount INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    "paymentMethod" TEXT DEFAULT 'balance',
    "tradeNo" TEXT,
    "paidAt" TIMESTAMPTZ(3),
    note TEXT,
    "expiresAt" TIMESTAMPTZ(3) NOT NULL DEFAULT (now() + interval '30 minutes'),
    "createdAt" TIMESTAMPTZ(3) DEFAULT now(),
    "updatedAt" TIMESTAMPTZ(3) DEFAULT now()
);
CREATE INDEX "PaymentOrder_userId_status_idx" ON "PaymentOrder"("userId", status);
CREATE INDEX "PaymentOrder_status_createdAt_idx" ON "PaymentOrder"(status, "createdAt");