# Official Node 24.14.0 bookworm-slim, linux/amd64, pinned to its platform manifest.
FROM public.ecr.aws/docker/library/node@sha256:4bd6219054c8bebcd26a66bfd8ca0bd6e1024b4b97474c59bb7ee3bbcbef4fe8
WORKDIR /app
RUN mkdir -p /app/src/channel_adapter /app/tests && chmod 0755 /app/src /app/src/channel_adapter /app/tests
COPY --chmod=0444 src/channel_adapter/hapi-adapter.mjs /app/src/channel_adapter/hapi-adapter.mjs
USER node
ENV NODE_ENV=production PORT=8318
EXPOSE 8318
ENTRYPOINT ["node", "/app/src/channel_adapter/hapi-adapter.mjs"]
