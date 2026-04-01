FROM node:22-alpine AS deps

WORKDIR /workspace/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder

WORKDIR /workspace/frontend

COPY --from=deps /workspace/frontend/node_modules ./node_modules
COPY frontend ./
RUN npm run build

FROM node:22-alpine AS runner

WORKDIR /workspace/frontend

ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

COPY --from=builder /workspace/frontend/.next/standalone ./
COPY --from=builder /workspace/frontend/.next/static ./.next/static

CMD ["node", "server.js"]
