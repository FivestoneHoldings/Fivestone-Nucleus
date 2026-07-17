/* GateWay app splash — v1.2
   The founder's note: "when you open the DoorDash app, you see the D and it loads
   and looks cool... make them feel like they're diving in, and the app is big /
   heavy / deep."

   So: the emblem lands first, a real progress bar fills, and the whole plate
   sinks INTO the page as it dissolves — you fall into the store, the page doesn't
   pop at you. Timing is generous on purpose; v1.1's 780ms felt like a glitch
   rather than an entrance.

   It shows once per session (sessionStorage), never on a page the user is just
   bouncing back to, and it respects prefers-reduced-motion. */
(function () {
  const KEY = 'gw_splashed';
  const REDUCED = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  window.gwSplash = function (opts) {
    opts = opts || {};
    const once = opts.once !== false;
    /* v1.9: time-gated, not forever-per-session. A founder demoing the app or a
       customer returning at dinner should get the entrance again; someone
       bouncing between pages shouldn't. 30-minute window. */
    try {
      if (once) {
        const last = parseInt(sessionStorage.getItem(KEY) || '0');
        if (Date.now() - last < 30 * 60 * 1000) return;
        sessionStorage.setItem(KEY, String(Date.now()));
      }
    } catch (e) {}

    const name = opts.name || 'GateWay';
    const sub = opts.sub || 'Local kitchens, delivered by your neighbors';
    const tint = opts.tint || '#16337a';
    const logo = opts.logo || '/static/gwd-emblem.png';
    const hold = REDUCED ? 260 : (opts.hold || 1500);

    const el = document.createElement('div');
    el.className = 'gws';
    el.setAttribute('aria-hidden', 'true');
    el.style.setProperty('--gws-tint', tint);
    el.innerHTML =
      '<div class="gws-plate">' +
        '<div class="gws-glow"></div>' +
        '<div class="gws-logo"><img src="' + logo + '" alt=""' +
          ' onerror="this.src=\'/static/gwd-emblem.png\'"></div>' +
        '<div class="gws-name"></div>' +
        '<div class="gws-sub"></div>' +
        '<div class="gws-track"><div class="gws-fill"></div></div>' +
        '<div class="gws-pow">Powered by GateWay' +
          '<span class="gws-dash"><i></i><i></i><i></i></span></div>' +
      '</div>';
    el.querySelector('.gws-name').textContent = name;
    el.querySelector('.gws-sub').textContent = sub;
    document.documentElement.appendChild(el);
    document.documentElement.style.overflow = 'hidden';

    const fill = el.querySelector('.gws-fill');
    requestAnimationFrame(() => {
      fill.style.transitionDuration = hold + 'ms';
      fill.style.width = '100%';
    });

    const done = () => {
      el.classList.add('gws-out');
      document.documentElement.style.overflow = '';
      setTimeout(() => el.remove(), REDUCED ? 60 : 620);
    };
    // Leave when the bar is full AND the page is actually ready — never rip the
    // curtain down on a half-drawn store.
    let bar = false, page = document.readyState === 'complete';
    const maybe = () => { if (bar && page) done(); };
    setTimeout(() => { bar = true; maybe(); }, hold);
    if (!page) window.addEventListener('load', () => { page = true; maybe(); });
    setTimeout(done, hold + 2600);   // hard ceiling: never trap anyone behind it
  };
})();
