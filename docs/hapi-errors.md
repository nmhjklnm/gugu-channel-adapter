# HAPI 专用实例（hapi-errors，#1）

Owner requested this HAPI-only exception on 2026-10-20. The New API binary stays the official pinned release. Protocol conversion, pricing and channel retry remain in New API. The adapter sends exactly one request to the fixed HAPI origin. It fixes only formats HAPI itself cannot read: the early error envelope below, and summary-only reasoning in Responses requests (see that section). All other request, model and tool bytes are preserved. It does not store a key or log prompts, headers or vendor response bodies.

## Error handling

Before response headers reach New API, inspect at most 64 KiB of SSE preface for at most 30 seconds. Comments, pings and empty start events can be held. Text, reasoning or tool output, an unknown event or a success terminal commits the original response; its remaining bytes pass through unchanged. The byte/time bound also commits, rather than failing a slow valid request. A failure after commitment cannot trigger adapter replay.

- Recognized `hapi_upstream_error` envelopes with a nested JSON `error` restore the upstream HTTP status and error object. A real parameter rejection stays 400; it is not retried as overload.
- Supplier 401/403 become 502 so they never imply that the Gugu user's credentials are invalid.
- Structured overload errors become 503, rate limits 429 and unclassified stream errors 502. Wrapped 504/524 stay unchanged; the gateway's retry exclusions remain authoritative.
- JSON error envelopes on 200/500 are normalized, buffering at most 1 MiB. Normal JSON and stream bytes are preserved. A compressed response is passed through; the adapter requests identity encoding to enable inspection.
- An interrupted/empty stream before commitment returns 502. After commitment it terminates the existing stream. Client disconnect aborts the HAPI connection.
- HTTP request IDs are preserved; IDs carried inside a HAPI wrapper are copied into JSON and the `x-hapi-upstream-request-id` / `x-hapi-upstream-trace-id` headers. `/healthz` exposes only aggregate request/error/active counts for path verification. Only hop-by-hop/framing headers are removed or recomputed.

## Summary-only reasoning (Responses requests)

Some upstreams in the same model pool return reasoning as `summary` only, with no `content` and no `encrypted_content`. kozeai does this for deepseek-v4.1-flash. After a gateway failover the next turn returns to HAPI, and Codex sends those items back as they are. HAPI reads reasoning only from `content`/`encrypted_content`. For a tool call made in thinking mode, the upstream then rejects the turn with 400 InvalidParameter, which the gateway does not retry.

For `/v1/responses` only, the adapter reads the request body. Each `input` reasoning item that has a non-empty `summary` and neither `content` nor `encrypted_content` gets `content: [{type: "reasoning_text", text: <summary texts joined by blank lines>}]`, and `content-length` is recomputed. A body with no such item, a body that is not JSON, and every other path are forwarded byte-identical. `/healthz` counts rewritten requests as `reasoning_filled`. New API has already read and size-checked the body, so buffering it adds no new bound.

This does not intercept 4router or v2api, fix other HAPI parameter compatibility, force migration of existing session bindings, or guarantee a replay after partial output. Known parameter compatibility is still handled by existing gateway routes/rules.

## Run and verify

`node --test tests/hapi-adapter.test.mjs` runs socket-level regression cases; the repository CI runs them alongside the Python rules and documentation contracts.

Implementation and deployment belong to `nmhjklnm/gugu-channel-adapter`, not `gugu-newapi`. The Node HTTP implementation was moved without changing its bytes; the Python launcher delegates this profile to Node 24. Other profiles continue to use the existing Python runtime. The new profile cannot mix Python request rules or change the fixed HAPI upstream.

From this repository root, build/start the dedicated private service using the gateway's existing Docker network:

```sh
HAPI_ADAPTER_NETWORK=<existing-network> docker compose -f deploy/hapi-errors/compose.yaml build
HAPI_ADAPTER_NETWORK=<existing-network> docker compose -f deploy/hapi-errors/compose.yaml up -d
```

Do not run a second service with the same `hapi-adapter` DNS alias beside an existing candidate. Read the device's current installation notes and arrange a controlled switch first. No host port is published. A successful health check alone is not acceptance; exercise actual relay requests and inspect the aggregate request counts.

For local development with Node 24 installed:

```sh
PROFILE=hapi-errors BIND=127.0.0.1 PORT=18318 PYTHONPATH=src python3 -m channel_adapter serve
```

After real requests pass, use the official New API management API to change only the selected HAPI channel Base URL to `http://hapi-adapter:8318`. Preserve existing routes, model mapping, keys, parameter rules and priorities. The gateway repository keeps only a link and its connection instructions; it does not carry this service's source, image or Compose definition.

Test a separate official New API instance against a synthetic HAPI failure through the adapter and a backup; check actual channel attempts and a successful final response. Also check that a wrapped 400 does not try the backup and an error after a tool call does not replay. Then test real HAPI through the adapter, including streams and tool-result round trips. Staging acceptance precedes any production changes.

## Rollback

Read the current channel first; restore only the Base URL changed by this operation, through the management API, if no subsequent edit superseded it. Then stop/remove only the owned adapter service. Do not restore an entire channel table or change the official gateway binary.
