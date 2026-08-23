const assert = require('node:assert/strict');

process.env.ADMIN_KEY = 'test-admin-key-that-is-long-enough';
const originalFetch = global.fetch;
global.fetch = async (url) => {
  if (String(url).includes('raw.githubusercontent.com')) {
    return { ok: false, status: 503, json: async () => ({}) };
  }
  throw new Error('Unexpected external request in admin test');
};
const { handler } = require('../../netlify/functions/admin');

async function run() {
  const anonymous = await handler({
    httpMethod: 'GET', headers: {}, queryStringParameters: null
  });
  assert.equal(anonymous.statusCode, 401);
  assert.match(anonymous.body, /method="POST"/);

  const rejected = await handler({
    httpMethod: 'POST', headers: {}, queryStringParameters: null,
    body: 'key=wrong'
  });
  assert.equal(rejected.statusCode, 401);

  const login = await handler({
    httpMethod: 'POST', headers: {}, queryStringParameters: null,
    body: 'key=test-admin-key-that-is-long-enough'
  });
  assert.equal(login.statusCode, 303);
  assert.equal(login.headers.Location, '/admin');
  assert.match(login.headers['Set-Cookie'], /HttpOnly; Secure; SameSite=Strict/);
  assert.doesNotMatch(login.headers['Set-Cookie'], /test-admin-key-that-is-long-enough/);

  const cookie = login.headers['Set-Cookie'].split(';')[0];
  const dashboard = await handler({
    httpMethod: 'GET', headers: { cookie }, queryStringParameters: null
  });
  assert.equal(dashboard.statusCode, 200);
  assert.match(dashboard.body, /System status/);
  assert.match(dashboard.body, /Metrics report:<\/strong> bundled fallback/);

  const logout = await handler({
    httpMethod: 'GET', headers: { cookie }, queryStringParameters: { logout: '1' }
  });
  assert.equal(logout.statusCode, 303);
  assert.match(logout.headers['Set-Cookie'], /Max-Age=0/);

  console.log('admin auth, metrics loading, diagnostics, and logout: OK');
  global.fetch = originalFetch;
}

run().catch(err => {
  console.error(err);
  process.exitCode = 1;
});
