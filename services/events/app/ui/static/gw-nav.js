/* GateWay shared bottom navigation.
 *
 * This markup and CSS was duplicated across seven pages, and four more pages
 * (the storefront, tracking, Neighbor Fund, roadmap) had no navigation at all —
 * a customer browsing a 273-item menu had no way out except the browser's back
 * button. One include now covers every consumer page, so a nav change happens
 * in one place instead of eleven.
 *
 * Usage:  <script src="/static/gw-nav.js" defer></script>
 * Opt out of a specific tab being marked active with:
 *         <body data-nav="order">   (defaults to matching the URL)
 * Suppress entirely (operator tools) by simply not including the script.
 */
(function () {
  if (window.__gwNavLoaded) return;
  window.__gwNavLoaded = true;

  var TABS = [
    { href: '/',          label: 'Home',     key: 'home',
      d: 'M3 10.5L12 3l9 7.5M5 9.5V21h14V9.5' },
    { href: '/order',     label: 'Order',    key: 'order',
      d: 'M6 7h12l-1 13H7L6 7zM9 7V5a3 3 0 0 1 6 0v2' },
    { href: '/courier',   label: 'Courier',  key: 'courier',
      d: 'M3 7h11v8H3zM14 10h4l3 3v2h-7zM7 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4z' },
    { href: '/activity',  label: 'Activity', key: 'activity',
      d: 'M12 21s-7-4.5-7-10a7 7 0 0 1 14 0c0 5.5-7 10-7 10zM12 11.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4z' },
    { href: '/me',        label: 'Account',  key: 'me',
      d: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5' }
  ];

  var CSS = [
    '.gw-nav{position:fixed;bottom:0;left:0;right:0;z-index:60;display:flex;justify-content:center;',
    'padding:0 12px max(10px, env(safe-area-inset-bottom));pointer-events:none;',
    'background:linear-gradient(180deg, rgba(247,248,251,0) 0%, rgba(247,248,251,.82) 45%, #f7f8fb 100%)}',
    '.gw-nav.gw-nav-dark{background:linear-gradient(180deg, rgba(14,21,38,0) 0%, rgba(14,21,38,.82) 45%, #0e1526 100%)}',
    '.gw-navin{pointer-events:auto;display:flex;gap:5px;align-items:center;',
    'background:rgba(14,21,38,.94);-webkit-backdrop-filter:blur(16px) saturate(1.5);',
    'backdrop-filter:blur(16px) saturate(1.5);border-radius:22px;padding:6px;',
    'border:1px solid rgba(255,255,255,.08);max-width:calc(100vw - 24px);',
    'box-shadow:0 12px 34px rgba(10,15,30,.34), 0 2px 8px rgba(10,15,30,.2),',
    'inset 0 1px 0 rgba(255,255,255,.09)}',
    '.gw-nav a{position:relative;display:flex;flex-direction:column;align-items:center;gap:3px;',
    'color:#8791a8;text-decoration:none;font-size:.58rem;font-weight:700;letter-spacing:.02em;',
    'padding:8px 8px 7px;border-radius:17px;font-family:"Archivo",system-ui,sans-serif;',
    'transition:color .2s ease,background .24s cubic-bezier(.2,1,.3,1);min-width:48px}',
    '.gw-nav a svg{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:1.9;',
    'stroke-linecap:round;stroke-linejoin:round}',
    '.gw-nav a.on{color:#fff;background:linear-gradient(135deg,#2f6fe0,#16337a)}',
    '.gw-nav a:active{transform:scale(.94)}',
    '@media (prefers-reduced-motion:reduce){.gw-nav a{transition:none}}',
    /* Pages that include the nav need room so it never covers real content. */
    'body.gw-has-nav{padding-bottom:96px}'
  ].join('');

  function activeKey() {
    var declared = document.body && document.body.getAttribute('data-nav');
    if (declared) return declared;
    var p = location.pathname;
    if (p === '/' || p === '') return 'home';
    if (p.indexOf('/order') === 0) return 'order';
    if (p.indexOf('/courier') === 0) return 'courier';
    if (p.indexOf('/activity') === 0 || p.indexOf('/track') === 0) return 'activity';
    if (p.indexOf('/me') === 0) return 'me';
    return '';
  }

  function build() {
    if (document.querySelector('.gw-nav')) return;   // page already has its own

    var style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);

    var active = activeKey();
    var nav = document.createElement('nav');
    nav.className = 'gw-nav';
    nav.setAttribute('aria-label', 'Main');
    if (document.body.getAttribute('data-nav-theme') === 'dark') {
      nav.className += ' gw-nav-dark';
    }
    var inner = document.createElement('div');
    inner.className = 'gw-navin';
    TABS.forEach(function (t) {
      var a = document.createElement('a');
      a.href = t.href;
      if (t.key === active) {
        a.className = 'on';
        a.setAttribute('aria-current', 'page');
      }
      a.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="' +
                    t.d + '"/></svg><span>' + t.label + '</span>';
      inner.appendChild(a);
    });
    nav.appendChild(inner);
    document.body.appendChild(nav);
    document.body.classList.add('gw-has-nav');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', build);
  } else {
    build();
  }
})();
