# Next.js production image (standalone output) for the Provenance web UI (review M-17).
# The browser talks to the Gateway at the HOST-published http://localhost:8000, so
# NEXT_PUBLIC_GATEWAY_URL is left at its default — no build arg needed.
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-slim AS run
WORKDIR /app
ENV NODE_ENV=production
# Standalone bundle: server.js + only the node_modules it actually needs.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
