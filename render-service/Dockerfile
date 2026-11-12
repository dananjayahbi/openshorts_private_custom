# Base images are pinned by digest (@sha256): the tag is only a label.
# To update one: docker buildx imagetools inspect <tag> and paste the new digest.
FROM node:18-bookworm-slim@sha256:f9ab18e354e6855ae56ef2b290dd225c1e51a564f87584b9bd21dd651838830e

# Install Chromium and FFmpeg for Remotion rendering
RUN apt-get update && \
    apt-get install -y --no-install-recommends chromium ffmpeg && \
    rm -rf /var/lib/apt/lists/*

ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ENV REMOTION_BUNDLE_PATH=/app/remotion
ENV OUTPUT_DIR=/output

WORKDIR /app

# Copy render service source
COPY render-service/package.json render-service/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Both copies of Remotion must be the same version. This lock pulls 4.0.446
# while remotion/package-lock.json pulls 4.0.541; webpack resolves 'remotion'
# from /app/node_modules, so @remotion/media 4.0.541 asked for the `Interactive`
# export that 4.0.446 does not have and every bundle died with
# "export 'Interactive' was not found in 'remotion'". --no-save keeps the
# committed lock files untouched.
RUN npm install --no-save --no-package-lock --no-audit --no-fund \
      remotion@4.0.541 @remotion/bundler@4.0.541 @remotion/renderer@4.0.541

COPY render-service/tsconfig.json ./
COPY render-service/src/ ./src/

# Copy remotion source for bundling
COPY remotion/package.json remotion/package-lock.json /app/remotion/
COPY remotion/tsconfig.json /app/remotion/tsconfig.json
COPY remotion/src/ /app/remotion/src/
COPY remotion/public/ /app/remotion/public/

# Install remotion deps
RUN cd /app/remotion && npm ci --no-audit --no-fund

# Build TypeScript
RUN npm run build

EXPOSE 3100
CMD ["node", "dist/server.js"]
