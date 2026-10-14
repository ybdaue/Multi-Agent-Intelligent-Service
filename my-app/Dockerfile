FROM node:24-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci

FROM node:24-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# next build 会加载 src/lib/env.ts 做环境变量校验。构建期不连库、不调外部服务，
# 故给占位值让校验通过；真实密钥由 runner 阶段经 compose environment 注入。
# NEXT_PUBLIC_* 会在构建期内联进 bundle，必须是最终值，由 compose build args 传入。
ARG NEXT_PUBLIC_BETTER_AUTH_URL=https://www.daueagent.cn
ARG NEXT_PUBLIC_API_URL=http://agents-api:8080
ENV NEXT_PUBLIC_BETTER_AUTH_URL=$NEXT_PUBLIC_BETTER_AUTH_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV DATABASE_URL="postgresql://build:build@localhost:5432/build"
ENV TICKFLOW_KEY="build-placeholder"

RUN npx prisma generate && npm run build

FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./
COPY --from=builder /app/prisma ./prisma
COPY --from=builder /app/prisma.config.ts ./
EXPOSE 3000
CMD ["sh", "-c", "npx prisma migrate deploy && npm start"]