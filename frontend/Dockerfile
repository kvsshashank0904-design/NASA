# MARS-X frontend (Next.js + CesiumJS). Not built on the development machine (Docker daemon not running there).
#
# NEXT_PUBLIC_* variables are inlined into the client bundle at build time, so the API URL
# must be supplied as a build argument (docker-compose.yml passes it).
#
# The Cesium static assets (Workers, Assets, Widgets, ThirdParty) are copied into
# public/cesium by a postinstall/prebuild script in package.json. The full source is
# therefore copied before `npm ci`, so that script exists when npm runs it.

FROM node:22-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_TELEMETRY_DISABLED=1
COPY . .
RUN npm ci
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    PORT=3000
COPY --from=build /app/package.json /app/package-lock.json ./
COPY --from=build /app/next.config.ts ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/public ./public
COPY --from=build /app/.next ./.next
EXPOSE 3000
CMD ["npm", "run", "start"]
