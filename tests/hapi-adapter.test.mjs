import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import { test } from 'node:test';
import { createHapiAdapter, normalizeHapiError } from '../src/channel_adapter/hapi-adapter.mjs';

const event = (value, ending = '\n') => Buffer.from(`data: ${JSON.stringify(value)}${ending}${ending}`);
const failure = { type: 'error', error: { type: 'hapi_upstream_error', message: 'HAPI upstream error: 400 {"error":{"type":"invalid_request_error","message":"unsupported max_tokens"}}' } };
async function fixture(t, handler, options = {}) {
  const upstream = http.createServer(handler);
  upstream.listen(0, '127.0.0.1'); await once(upstream, 'listening');
  const adapter = createHapiAdapter({ upstream: `http://127.0.0.1:${upstream.address().port}`, ...options });
  adapter.listen(0, '127.0.0.1'); await once(adapter, 'listening');
  t.after(async () => {
    await Promise.all([adapter, upstream].map(s => new Promise(resolve => { s.close(resolve); s.closeAllConnections(); })));
  });
  return `http://127.0.0.1:${adapter.address().port}`;
}
const post = (base, path = '/v1/responses', extra = {}) => fetch(base + path, { method: 'POST', body: '{"model":"sarah/gpt-6-luna"}', ...extra });

test('wrapped 400 is restored, supplier credentials do not become client authentication errors', () => {
  assert.equal(normalizeHapiError(failure).status, 400);
  for (const code of [401, 403]) assert.equal(normalizeHapiError({ error: { type: 'hapi_upstream_error', message: `HAPI upstream error: ${code} {"error":{"message":"bad upstream key"}}` } }).status, 502);
  for (const code of [429, 500, 503, 504, 524]) assert.equal(normalizeHapiError({ error: { type: 'hapi_upstream_error', message: `HAPI upstream error: ${code} {"error":{"message":"failure"}}` } }).status, code);
  assert.equal(normalizeHapiError({ output: [{ text: 'error: overloaded' }] }), null);
});

for (const path of ['/v1/messages', '/v1/responses', '/v1/chat/completions']) {
  test(`fragmented SSE wrapped rejection becomes HTTP 400 for ${path}`, async t => {
    let hits = 0;
    const base = await fixture(t, (_q, s) => {
      hits++; s.writeHead(200, { 'content-type': 'text/event-stream', 'x-request-id': 'vendor-request-37' });
      const bytes = Buffer.concat([Buffer.from(': ping\r\n\r\n'), event({ type: 'ping' }, '\r\n'), event(failure, '\r\n')]);
      let i = 0;
      const timer = setInterval(() => { if (i === bytes.length) { clearInterval(timer); s.end(); } else s.write(bytes.subarray(i, ++i)); }, 1);
      s.once('close', () => clearInterval(timer));
    });
    const r = await post(base, path); assert.equal(r.status, 400); assert.equal(r.headers.get('x-request-id'), 'vendor-request-37');
    const body = await r.json(); assert.equal(body.error.message, 'unsupported max_tokens');
    if (path === '/v1/messages') assert.equal(body.type, 'error');
    assert.equal(hits, 1);
  });
}

test('Responses metadata followed by overload produces HTTP 503 without leaking a successful preface', async t => {
  const base = await fixture(t, (_q, s) => {
    s.writeHead(200, { 'content-type': 'text/event-stream' });
    s.end(Buffer.concat([event({ type: 'response.created', response: { output: [] } }), event({ type: 'response.failed', response: { error: { code: 'server_overloaded', message: 'at capacity' } } })]));
  });
  const r = await post(base); assert.equal(r.status, 503); assert.equal((await r.json()).error.code, 'server_overloaded');
});

test('JSON error envelopes are unwrapped on 200 and 500', async t => {
  for (const code of [200, 500]) {
    const base = await fixture(t, (_q, s) => { s.writeHead(code, { 'content-type': 'application/json', 'content-encoding': 'identity' }); s.end(JSON.stringify(failure)); });
    const r = await post(base); assert.equal(r.status, 400); assert.equal(r.headers.get('content-encoding'), null); assert.equal((await r.json()).error.type, 'invalid_request_error');
  }
});

test('rate limit and unknown structured stream errors become retryable statuses', async t => {
  for (const [error, code] of [[{ type: 'rate_limit_error', message: 'slow down' }, 429], [{ type: 'unknown_vendor_failure', message: 'failed' }, 502]]) {
    const base = await fixture(t, (_q, s) => { s.writeHead(200, { 'content-type': 'text/event-stream' }); s.end(event({ type: 'error', error })); });
    assert.equal((await post(base)).status, code);
  }
});

for (const output of [
  { type: 'content_block_start', index: 0, content_block: { type: 'tool_use', id: 'tool-37', name: 'add', input: {} } },
  { type: 'response.output_item.added', item: { type: 'function_call', name: 'add', call_id: 'call-37' } },
  { type: 'response.output_text.delta', delta: '你好，error 是普通文字' },
  { type: 'response.reasoning_summary_text.delta', delta: 'Thinking' },
]) {
  test(`after ${output.type} no error rewrite or request replay`, async t => {
    const raw = Buffer.concat([event(output), event(failure)]); let hits = 0;
    const base = await fixture(t, (_q, s) => { hits++; s.writeHead(200, { 'content-type': 'text/event-stream' }); s.end(raw); });
    const r = await post(base); assert.equal(r.status, 200); assert.deepEqual(Buffer.from(await r.arrayBuffer()), raw); assert.equal(hits, 1);
  });
}

test('normal request, auth and response bytes survive; hop-by-hop headers do not', async t => {
  const body = Buffer.from('{ "model": "sarah/gpt-6-luna", "tools":[{"type":"custom","name":"计算"}] }');
  const answer = Buffer.from('{ "output": [{"text":"你好，error"}] }');
  let received;
  const base = await fixture(t, async (q, s) => {
    const chunks = []; for await (const c of q) chunks.push(c);
    received = { body: Buffer.concat(chunks), key: q.headers.authorization, encoding: q.headers['accept-encoding'], extra: q.headers['x-private-hop'] };
    s.writeHead(200, { 'content-type': 'application/json', 'x-request-id': 'r37' }); s.end(answer);
  });
  const r = await new Promise((resolve, reject) => {
    const q = http.request(base + '/v1/responses', { method: 'POST', headers: { Authorization: 'Bearer test-only-key', Connection: 'x-private-hop', 'x-private-hop': 'remove' } }, async response => {
      const chunks = []; for await (const chunk of response) chunks.push(chunk);
      resolve({ status: response.statusCode, body: Buffer.concat(chunks) });
    });
    q.once('error', reject); q.end(body);
  });
  assert.equal(r.status, 200); assert.deepEqual(r.body, answer);
  assert.deepEqual(received, { body, key: 'Bearer test-only-key', encoding: 'identity', extra: undefined });
});

test('bounded prefix and deadline release ordinary bytes without unbounded buffering', async t => {
  for (const options of [{ prefixLimit: 16 }, { prefixWaitMs: 10 }]) {
    const first = event({ type: 'ping' }); const last = event(failure);
    const base = await fixture(t, (_q, s) => { s.writeHead(200, { 'content-type': 'text/event-stream' }); s.write(first); setTimeout(() => s.end(last), 30); }, options);
    const r = await post(base); assert.equal(r.status, 200); assert.deepEqual(Buffer.from(await r.arrayBuffer()), Buffer.concat([first, last]));
  }
});

test('EOF with only metadata fails before commit; terminal success is preserved', async t => {
  for (const [raw, status] of [[event({ type: 'ping' }), 502], [event({ type: 'response.completed', response: { output: [] } }), 200]]) {
    const base = await fixture(t, (_q, s) => { s.writeHead(200, { 'content-type': 'text/event-stream' }); s.end(raw); });
    const r = await post(base); assert.equal(r.status, status); await r.arrayBuffer();
  }
});

test('client disconnect cancels the in-flight HAPI request', async t => {
  let connected; const ready = new Promise(r => { connected = r; });
  let cancelled; const closed = new Promise(r => { cancelled = r; });
  const base = await fixture(t, (_q, s) => { s.writeHead(200, { 'content-type': 'text/event-stream' }); s.write(event({ type: 'ping' })); s.once('close', cancelled); connected(); });
  const request = http.request(base + '/v1/responses', { method: 'POST' }); request.on('error', () => {}); request.end('{}');
  await ready; request.destroy();
  await Promise.race([closed, new Promise((_, reject) => { const timer = setTimeout(() => reject(Error('upstream not cancelled')), 1000); timer.unref(); })]);
});

test('reject absolute targets, unknown paths and do not forward health checks', async t => {
  let hits = 0; const base = await fixture(t, (_q, s) => { hits++; s.end(); });
  const health = await fetch(base + '/healthz'); assert.equal(health.status, 200); assert.deepEqual(await health.json(), { ok: true, requests: 0, normalized_errors: 0, reasoning_filled: 0, active_requests: 0 });
  assert.equal((await post(base, '//example.com/v1/messages')).status, 404);
  assert.equal((await post(base, '/api/channel/')).status, 404);
  assert.equal(hits, 0);
});


test('preserves request and trace IDs carried inside the HAPI wrapper', async t => {
  const error = { type: 'hapi_upstream_error', message: 'HAPI upstream error: 400 '+JSON.stringify({ error: { type: 'invalid_request_error', message: 'bad parameter' }, request_id: 'vendor-37', trace_id: 'trace-37' }) };
  const base = await fixture(t, (_q, s) => { s.writeHead(200, { 'content-type': 'text/event-stream' }); s.end(event({ type: 'error', error })); });
  const r = await post(base); const body = await r.json();
  assert.equal(r.status, 400); assert.equal(body.request_id, 'vendor-37'); assert.equal(body.trace_id, 'trace-37');
  assert.equal(r.headers.get('x-hapi-upstream-request-id'), 'vendor-37');
  assert.equal(r.headers.get('x-hapi-upstream-trace-id'), 'trace-37');
});

test('summary-only reasoning in a Responses body gets content; other bodies pass byte-identical', async t => {
  const seen = [];
  const base = await fixture(t, async (q, s) => {
    const chunks = []; for await (const c of q) chunks.push(c);
    seen.push({ body: Buffer.concat(chunks), length: q.headers['content-length'] });
    s.writeHead(200, { 'content-type': 'application/json' }); s.end('{}');
  });
  const foreign = { input: [{ type: 'reasoning', summary: [{ type: 'summary_text', text: 'a' }, { type: 'summary_text', text: 'b' }] },
    { type: 'function_call', name: 'shell', arguments: '{}', call_id: 'c1' }] };
  await post(base, '/v1/responses', { body: JSON.stringify(foreign) });
  const sent = JSON.parse(seen[0].body);
  assert.deepEqual(sent.input[0].content, [{ type: 'reasoning_text', text: 'a\n\nb' }]);
  assert.deepEqual(sent.input[1], foreign.input[1]);
  assert.equal(Number(seen[0].length), seen[0].body.length);
  assert.equal((await (await fetch(base + '/healthz')).json()).reasoning_filled, 1);
  const own = '{ "input": [{"type":"reasoning","summary":[],"content":[{"type":"reasoning_text","text":"x"}],"encrypted_content":"h"}] }';
  for (const [path, body] of [['/v1/responses', own], ['/v1/responses', 'not json'], ['/v1/messages', JSON.stringify(foreign)]]) {
    await post(base, path, { body });
    assert.equal(seen.at(-1).body.toString(), body, path);
  }
});

test('chunked Responses requests: the filled body is sent with content-length and no transfer-encoding', async t => {
  const seen = [];
  const base = await fixture(t, async (q, s) => {
    const chunks = []; for await (const c of q) chunks.push(c);
    seen.push({ body: Buffer.concat(chunks), length: q.headers['content-length'], te: q.headers['transfer-encoding'] });
    s.writeHead(200, { 'content-type': 'application/json' }); s.end('{}');
  });
  const send = (path, body) => new Promise((resolve, reject) => {
    const q = http.request(base + path, { method: 'POST', headers: { 'transfer-encoding': 'chunked' } }, r => { r.resume(); r.once('end', resolve); });
    q.once('error', reject);
    const half = Math.floor(body.length / 2); q.write(body.subarray(0, half)); q.end(body.subarray(half));
  });
  const foreign = Buffer.from(JSON.stringify({ input: [{ type: 'reasoning', summary: [{ type: 'summary_text', text: 'r' }] }] }));
  const own = Buffer.from('{ "input": [{"type":"message","role":"user","content":"hi"}] }');
  await send('/v1/responses', foreign);
  assert.equal(seen[0].te, undefined); assert.equal(Number(seen[0].length), seen[0].body.length);
  assert.deepEqual(JSON.parse(seen[0].body).input[0].content, [{ type: 'reasoning_text', text: 'r' }]);
  await send('/v1/responses', own);
  assert.deepEqual(seen[1].body, own); assert.ok(!(seen[1].te && seen[1].length), 'never both transfer-encoding and content-length');
  await send('/v1/messages', own);
  assert.deepEqual(seen[2].body, own); assert.equal(seen[2].te, 'chunked'); assert.equal(seen[2].length, undefined);
});
