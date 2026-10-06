# Frontend de Sebasanalisis (Next.js).
#
# OJO con NEXT_PUBLIC_API_BASE_URL: Next lo incrusta en el JavaScript del
# navegador DURANTE EL BUILD, no lo lee al arrancar. Por eso entra como
# build arg y no solo como variable de entorno del contenedor. En Dokploy hay
# que declararlo en "Build Arguments", no unicamente en "Environment".
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL

# DSN del proyecto del frontend en GlitchTip. Igual que el anterior, se incrusta
# en el build. Sin el, el monitoreo de errores queda desactivado.
ARG NEXT_PUBLIC_SENTRY_DSN
ENV NEXT_PUBLIC_SENTRY_DSN=$NEXT_PUBLIC_SENTRY_DSN

RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000

RUN addgroup --system --gid 1001 nodejs \
 && adduser --system --uid 1001 nextjs

# La salida "standalone" trae su propio server.js con las dependencias minimas.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
