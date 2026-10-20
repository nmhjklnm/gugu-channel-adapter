import http from 'node:http';
import https from 'node:https';
import { once } from 'node:events';
import { pathToFileURL } from 'node:url';

const HAPI = 'https://hapi.hc11.org';
const HOP_HEADERS = new Set(['connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade']);
const PATHS = /^\/v1\/(?:messages(?:\/count_tokens)?|responses(?:\/compact)?|chat\/completions|models)$/;

function headersWithoutHop(headers) {
  const excluded = new Set([...HOP_HEADERS, ...(headers.connection || '').toLowerCase().split(',').map(s => s.trim())]);
  return Object.fromEntries(Object.entries(headers).filter(([key]) => !excluded.has(key.toLowerCase())));
}

// Only structured protocol errors qualify. Text mentioning errors is ordinary model output.
export function normalizeHapiError(value, httpStatus = 200) {
  let error = value?.error || value?.response?.error;
  if (!error || typeof error !== 'object' || Array.isArray(error)) return null;
  let status;
  let requestId = value.request_id || value.response?.request_id;
  let traceId = value.trace_id || value.response?.trace_id;
  if (error.type === 'hapi_upstream_error' && typeof error.message === 'string') {
    const wrapped = /^HAPI upstream error:\s*(\d{3})\s+([\s\S]+)$/.exec(error.message);
    if (wrapped) {
      try {
        const parsed = JSON.parse(wrapped[2]);
        if (parsed?.error && typeof parsed.error === 'object' && !Array.isArray(parsed.error)) {
          status = Number(wrapped[1]);
          requestId = parsed.request_id || requestId;
          traceId = parsed.trace_id || traceId;
          error = parsed.error;
        }
      } catch { /* An unrecognized HAPI envelope remains an upstream failure. */ }
    }
  }
  const code = String(error.code || error.type || '');
  if (!status) {
    if (/^(?:invalid_request_error|invalid_request|context_length_exceeded|bad_request)$/.test(code)) status = 400;
    else if (/^(?:rate_limit_error|rate_limit_exceeded|too_many_requests)$/.test(code)) status = 429;
    else if (/^(?:overloaded_error|server_overloaded|serverOverloaded|server_error|api_error)$/.test(code)) status = 503;
    else status = httpStatus >= 400 ? httpStatus : 502;
  }
  // These credentials belong to HAPI's upstream, never to the Gugu end user.
  if (status === 401 || status === 403) status = 502;
  if (status < 400 || status > 599) status = 502;
  return { status, ...(typeof requestId === 'string' ? { requestId: requestId.slice(0, 256) } : {}), ...(typeof traceId === 'string' ? { traceId: traceId.slice(0, 256) } : {}), error: { type: String(error.type || 'upstream_error'), message: String(error.message || 'HAPI upstream failed'), ...(error.code != null ? { code: error.code } : {}), ...(error.param != null ? { param: error.param } : {}) } };
}

function sseValue(frame) {
  const data = frame.toString('utf8').split(/\r\n|\r|\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).replace(/^ /, '')).join('\n');
  if (!data || data === '[DONE]') return { terminal: data === '[DONE]', hold: true };
  let value;
  try { value = JSON.parse(data); } catch { return { hold: false }; }
  const failure = normalizeHapiError(value);
  if (failure) return { failure };
  const type = value.type;
  if (type === 'ping' || type === 'response.created' || type === 'response.in_progress') {
    // Unexpected initial output is already observable: never replay it.
    return { hold: !value.response?.output?.length };
  }
  if (type === 'message_start') return { hold: !value.message?.content?.length };
  if (type === 'content_block_start') return { hold: value.content_block?.type === 'text' && !value.content_block.text };
  if (Array.isArray(value.choices)) {
    return { hold: value.choices.length > 0 && value.choices.every(c => !c.finish_reason && c.delta && Object.keys(c.delta).every(k => k === 'role' || k === 'content' && !c.delta.content)) };
  }
  return { hold: false };
}

export function createHapiAdapter({ upstream = HAPI, prefixLimit = 64 * 1024, prefixWaitMs = 30_000, idleTimeoutMs = 120_000, jsonLimit = 1024 * 1024 } = {}) {
  const target = new URL(upstream);
  if (!['http:', 'https:'].includes(target.protocol) || target.username || target.password || target.search || target.hash) throw Error('Invalid fixed HAPI upstream');
  const transport = target.protocol === 'https:' ? https : http;
  const agent = new transport.Agent({ keepAlive: true, maxSockets: 128, maxFreeSockets: 16 });
  const active = new Set();
  let requests = 0, normalizedErrors = 0;
  const server = http.createServer({ requestTimeout: 120_000, headersTimeout: 30_000, maxHeaderSize: 32 * 1024 }, (req, res) => {
    if (req.method === 'GET' && req.url === '/healthz') { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify({ ok: true, requests, normalized_errors: normalizedErrors, active_requests: active.size })); return; }
    const path = req.url?.split('?')[0];
    if (!req.url?.startsWith('/') || req.url.startsWith('//') || !PATHS.test(path) || !(path === '/v1/models' ? req.method === 'GET' : req.method === 'POST')) {
      res.writeHead(404); res.end(); return;
    }
    requests++;
    const controller = new AbortController();
    let response;
    const requestHeaders = headersWithoutHop(req.headers);
    delete requestHeaders.host;
    requestHeaders['accept-encoding'] = 'identity';
    const outgoing = transport.request({ protocol: target.protocol, hostname: target.hostname, port: target.port, path: target.pathname.replace(/\/$/, '') + req.url, method: req.method, headers: requestHeaders, agent, signal: controller.signal });
    active.add(outgoing);
    outgoing.once('close', () => active.delete(outgoing));
    outgoing.setTimeout(idleTimeoutMs, () => outgoing.destroy(new Error('HAPI upstream idle timeout')));
    req.once('aborted', () => controller.abort());
    req.once('error', () => controller.abort());
    res.once('close', () => { if (!res.writableFinished) controller.abort(); });

    function fail(failure, upstreamHeaders = {}) {
      if (res.headersSent || res.destroyed) return;
      normalizedErrors++;
      const outputHeaders = headersWithoutHop(upstreamHeaders);
      for (const name of ['content-length', 'content-type', 'content-encoding', 'etag']) delete outputHeaders[name];
      const identifiers = { ...(failure.requestId ? { request_id: failure.requestId } : {}), ...(failure.traceId ? { trace_id: failure.traceId } : {}) };
      if (/^[A-Za-z0-9._:/-]{1,256}$/.test(failure.requestId || '')) outputHeaders['x-hapi-upstream-request-id'] = failure.requestId;
      if (/^[A-Za-z0-9._:/-]{1,256}$/.test(failure.traceId || '')) outputHeaders['x-hapi-upstream-trace-id'] = failure.traceId;
      const body = Buffer.from(JSON.stringify({ ...(path === '/v1/messages' ? { type: 'error' } : {}), error: failure.error, ...identifiers }));
      res.writeHead(failure.status, { ...outputHeaders, 'content-type': 'application/json', 'content-length': body.length, 'x-gugu-hapi-adapter': 'normalized' });
      res.end(body);
      response?.destroy();
      outgoing.destroy();
    }
    outgoing.once('error', () => {
      if (!res.headersSent && !controller.signal.aborted) fail({ status: 502, error: { type: 'upstream_error', code: 'hapi_transport_error', message: 'HAPI upstream connection failed' } });
      else if (!res.writableFinished) res.destroy();
    });
    outgoing.once('response', async incoming => {
      response = incoming;
      const rawHeaders = headersWithoutHop(incoming.headers);
      const status = incoming.statusCode || 502;
      let pending = Buffer.alloc(0), scan = 0, committed = false;
      let queue = Promise.resolve();
      const send = async chunk => {
        if (!chunk.length) return;
        if (!res.write(chunk)) await once(res, 'drain', { signal: controller.signal });
      };
      const commit = async () => {
        if (committed) return;
        committed = true;
        res.writeHead(status, rawHeaders);
        const buffered = pending;
        pending = Buffer.alloc(0);
        await send(buffered);
      };
      const sse = String(rawHeaders['content-type'] || '').toLowerCase().includes('text/event-stream');
      const json = String(rawHeaders['content-type'] || '').toLowerCase().includes('json');
      // Serialize the deadline with chunk processing so bytes cannot be reordered around backpressure.
      const timer = setTimeout(() => { queue = queue.then(commit).catch(() => { controller.abort(); res.destroy(); }); }, prefixWaitMs);
      timer.unref();
      try {
        if (!sse && !json || rawHeaders['content-encoding'] && rawHeaders['content-encoding'] !== 'identity') await commit();
        for await (const chunk of incoming) {
          queue = queue.then(async () => {
            if (committed) { await send(chunk); return; }
            if (pending.length + chunk.length > (sse ? prefixLimit : jsonLimit)) {
              await commit(); await send(chunk); return;
            }
            pending = Buffer.concat([pending, chunk]);
            if (!sse) return;
            for (;;) {
              const match = /\r\n\r\n|\n\n|\r\r|\r\n\n|\n\r\n/.exec(pending.subarray(scan).toString('latin1'));
              if (!match) break;
              const end = scan + match.index + match[0].length;
              const event = sseValue(pending.subarray(scan, end));
              scan = end;
              if (event.failure) { clearTimeout(timer); fail(event.failure, rawHeaders); return; }
              if (!event.hold || event.terminal) { await commit(); return; }
            }
          });
          await queue;
          if (res.writableEnded || controller.signal.aborted) return;
        }
        clearTimeout(timer);
        await queue;
        if (res.writableEnded || controller.signal.aborted) return;
        if (!committed && json) {
          let failure;
          try { failure = normalizeHapiError(JSON.parse(pending.toString('utf8')), status); } catch { /* Preserve ordinary vendor responses. */ }
          if (failure) { fail(failure, rawHeaders); return; }
        }
        if (!committed && sse) {
          fail({ status: 502, error: { type: 'upstream_error', code: 'hapi_stream_incomplete', message: 'HAPI stream ended before output or a terminal event' } }, rawHeaders);
          return;
        }
        await commit(); res.end();
      } catch {
        if (!res.headersSent && !controller.signal.aborted) fail({ status: 502, error: { type: 'upstream_error', code: 'hapi_stream_interrupted', message: 'HAPI response was interrupted' } }, rawHeaders);
        else if (!res.writableFinished) res.destroy();
      } finally { clearTimeout(timer); }
    });
    // Native HTTP piping keeps request bytes and backpressure intact; the adapter never parses prompts/tools.
    req.pipe(outgoing);
  });
  server.once('close', () => { for (const request of active) request.destroy(); agent.destroy(); });
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const server = createHapiAdapter();
  server.listen(Number(process.env.PORT || 8318), process.env.HOST || '0.0.0.0');
  const stop = () => { server.close(); setTimeout(() => server.closeAllConnections(), 10_000).unref(); };
  process.once('SIGTERM', stop); process.once('SIGINT', stop);
}
