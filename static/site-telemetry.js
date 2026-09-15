/* Native Vercel collection on the official site only. No business events or IDs. */
(() => {
  const routes = new Set([
    '/', '/en', '/security', '/en/security', '/open-source', '/en/open-source',
    '/harvey-alternative', '/en/harvey-alternative', '/features', '/en/features',
    '/landing', '/login', '/demo', '/spaces', '/agent', '/guide',
    '/model', '/config', '/skills', '/risks',
  ]);
  function safeURL(value) {
    try {
      const url = new URL(value, location.origin);
      if (url.origin !== 'https://openharvey.com' || !routes.has(url.pathname)) return null;
      return url.origin + url.pathname;
    } catch { return null; }
  }
  if (window.top !== window || !safeURL(location.href) || window.openHarveyTelemetryStarted) return;
  window.openHarveyTelemetryStarted = true;

  // Keep query strings out of HTTP Referer headers as well as the event payload.
  const policy = document.createElement('meta');
  policy.name = 'referrer'; policy.content = 'strict-origin';
  document.head.appendChild(policy);
  function beforeSend(event) {
    const url = safeURL(event.url);
    if (!safeURL(location.href) || !url || !['pageview', 'vital'].includes(event.type)) return null;
    // Native Analytics suppresses same-host referrers. Drop unsafe external
    // referrals rather than send query strings or private resource paths.
    if (event.type === 'pageview' && document.referrer) {
      try {
        const ref = new URL(document.referrer);
        if (ref.host !== location.host && (ref.search || ref.hash || /^\/(api|ops|auth)(\/|$)/.test(ref.pathname))) return null;
      } catch { return null; }
    }
    return { ...event, url };
  }
  window.va = window.va || function () { (window.vaq = window.vaq || []).push(arguments); };
  window.si = window.si || function () { (window.siq = window.siq || []).push(arguments); };
  window.va('beforeSend', beforeSend);
  window.si('beforeSend', beforeSend);
  for (const name of ['insights', 'speed-insights']) {
    const script = document.createElement('script');
    script.src = '/_vercel/' + name + '/script.js';
    script.defer = true; script.referrerPolicy = 'no-referrer';
    script.dataset.route = location.pathname;
    document.head.appendChild(script);
  }
})();
