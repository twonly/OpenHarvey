import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../static/site-telemetry.js', import.meta.url), 'utf8');
function boot(href, { referrer = '', iframe = false } = {}) {
  const appended = [], window = {};
  window.top = iframe ? {} : window;
  const context = vm.createContext({ window, URL, location: new URL(href), document: {
    referrer, head: { appendChild: node => appended.push(node) },
    createElement: tag => ({ tag, dataset: {} }),
  }});
  vm.runInContext(source, context);
  return { window, appended, context, filter: window.vaq?.[0][1] };
}

test('only official top-level product pages load native collectors, once', () => {
  const value = boot('https://openharvey.com/agent#contract-secret');
  assert.deepEqual(value.appended.filter(x => x.tag === 'script').map(x => x.src), [
    '/_vercel/insights/script.js', '/_vercel/speed-insights/script.js',
  ]);
  assert.equal(value.appended[0].content, 'strict-origin');
  vm.runInContext(source, value.context);
  assert.equal(value.appended.length, 3);
  for (const url of ['https://openharvey.com/ops', 'https://openharvey.com/ops/detail?id=secret',
    'https://openharvey.com/traces', 'https://openharvey.com/members',
    'https://openharvey.com/api/artifacts/secret/preview', 'https://openharvey.com/auth/callback?code=secret',
    'https://openharvey.com/agent/secret', 'https://agent.tokrace.com/agent',
    'http://localhost:8000/agent', 'https://preview.vercel.app/']) {
    assert.equal(boot(url).appended.length, 0, url);
  }
  assert.equal(boot('https://openharvey.com/', { iframe: true }).appended.length, 0);
});

test('native beforeSend strips queries and fragments, rejects identity and excluded routes', () => {
  const value = boot('https://openharvey.com/agent?email=secret#document-secret');
  for (const type of ['pageview', 'vital']) {
    const event = value.filter({ type, url: 'https://openharvey.com/agent?email=secret#document-secret' });
    assert.equal(event.url, 'https://openharvey.com/agent');
    assert.equal(JSON.stringify(event).includes('secret'), false);
  }
  assert.equal(value.filter({ type: 'event', url: 'https://openharvey.com/agent', payload: { userId: 'secret' } }), null);
  assert.equal(value.filter({ type: 'pageview', url: 'https://openharvey.com/ops' }), null);
  value.context.location = new URL('https://openharvey.com/ops');
  assert.equal(value.filter({ type: 'vital', url: 'https://openharvey.com/agent' }), null);
});

test('unsafe external referrers are excluded while ordinary source attribution survives', () => {
  for (const referrer of ['https://example.com/?email=secret', 'https://example.com/api/files/secret',
    'https://agent.tokrace.com/ops/detail']) {
    assert.equal(boot('https://openharvey.com/', { referrer }).filter({ type: 'pageview', url: 'https://openharvey.com/' }), null);
  }
  assert.ok(boot('https://openharvey.com/', { referrer: 'https://www.google.com/' })
    .filter({ type: 'pageview', url: 'https://openharvey.com/' }));
});

test('public exporter and app entry pages keep collection wiring and ops excluded', () => {
  for (const file of ['index', 'spaces', 'demo', 'guide', 'landing']) {
    assert.match(readFileSync(new URL(`../static/${file}.html`, import.meta.url), 'utf8'), /site-telemetry\.js/);
  }
  assert.doesNotMatch(readFileSync(new URL('../static/ops.html', import.meta.url), 'utf8'), /site-telemetry\.js/);
});
