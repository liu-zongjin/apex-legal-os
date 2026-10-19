// Pages is only an HTTPS entrance. Auth, assets, D1 and rate limiting stay in
// the existing Worker, called privately without resolving its workers.dev URL.
export default {
  async fetch(request, env) {
    try {
      if (!env.ADMIN) throw new Error('missing_service');
      return await env.ADMIN.fetch(request);
    } catch {
      return new Response('后台暂时无法连接，请稍后重试。', {
        status: 503,
        headers: {'Content-Type':'text/plain; charset=utf-8','Cache-Control':'no-store',
          'X-Content-Type-Options':'nosniff','Retry-After':'30'}
      });
    }
  }
};
