/* GateWay UI kit: branded bottom-sheet dialogs + toasts (replaces prompt/confirm/alert). */
(function(){
  const dark = document.body && getComputedStyle(document.body).backgroundColor
    .match(/\d+/g)?.slice(0,3).map(Number).reduce((a,b)=>a+b,0) < 200;
  const P = dark
    ? {sheet:'#131a30', ink:'#e8e6e1', dim:'#8b93a7', line:'#263252', field:'#0e1526'}
    : {sheet:'#ffffff', ink:'#14181f', dim:'#5a5e64', line:'#e4e8f2', field:'#f2f4fa'};
  const css = document.createElement('style');
  css.textContent = `
  .gwd-ov{position:fixed;inset:0;background:rgba(8,12,24,.55);z-index:200;display:flex;
    align-items:flex-end;justify-content:center;opacity:0;transition:opacity .18s}
  .gwd-ov.on{opacity:1}
  .gwd{background:${P.sheet};color:${P.ink};width:100%;max-width:480px;border-radius:22px 22px 0 0;
    padding:22px 20px calc(20px + env(safe-area-inset-bottom));transform:translateY(24px);
    transition:transform .2s ease;box-shadow:0 -10px 40px rgba(0,0,0,.35)}
  .gwd-ov.on .gwd{transform:none}
  .gwd h3{font-size:1.05rem;font-weight:800;margin:0 0 6px}
  .gwd p{font-size:.86rem;color:${P.dim};margin:0 0 14px;line-height:1.5}
  .gwd input,.gwd textarea{width:100%;box-sizing:border-box;background:${P.field};color:${P.ink};
    border:1.5px solid transparent;border-radius:12px;padding:13px;font-family:inherit;
    font-size:.95rem;margin-bottom:14px}
  .gwd input:focus,.gwd textarea:focus{border-color:#2f6fe0;outline:none;background:${dark?'#0e1526':'#fff'}}
  .gwd .r{display:flex;gap:10px}
  .gwd button{flex:1;padding:14px;border-radius:13px;border:none;font-weight:800;
    font-family:inherit;font-size:.92rem;cursor:pointer}
  .gwd .go{background:linear-gradient(135deg,#16337a,#1e4292);color:#fff}
  .gwd .go.danger{background:linear-gradient(135deg,#a81620,#d81f2a)}
  .gwd .no{background:transparent;color:${P.dim};border:1.5px solid ${P.line}}
  .gwt{position:fixed;left:50%;bottom:calc(26px + env(safe-area-inset-bottom));transform:translateX(-50%) translateY(12px);
    background:#0e1526;color:#e8eaf0;padding:12px 20px;border-radius:30px;font-weight:700;
    font-size:.85rem;z-index:210;opacity:0;transition:all .22s;box-shadow:0 8px 26px rgba(0,0,0,.35);
    max-width:86vw;text-align:center}
  .gwt.on{opacity:1;transform:translateX(-50%)}
  .gwt.bad{background:#d81f2a;color:#fff}
  @media (prefers-reduced-motion: reduce){.gwd-ov,.gwd,.gwt{transition:none}}`;
  document.head.appendChild(css);

  function esc(x){ const d=document.createElement('div'); d.textContent=x||''; return d.innerHTML; }

  function sheet(opts, withInput){
    return new Promise(resolve => {
      const ov = document.createElement('div'); ov.className = 'gwd-ov';
      const multiline = !!opts.multiline;
      ov.innerHTML = `<div class="gwd" role="dialog" aria-modal="true">
        <h3>${esc(opts.title||'')}</h3>
        ${opts.body?`<p>${esc(opts.body)}</p>`:''}
        ${withInput?(multiline
          ?`<textarea id="gwdIn" rows="3" placeholder="${esc(opts.placeholder||'')}">${esc(opts.value||'')}</textarea>`
          :`<input id="gwdIn" inputmode="${esc(opts.inputmode||'text')}" placeholder="${esc(opts.placeholder||'')}" value="${esc(opts.value||'')}">`):''}
        <div class="r">
          <button class="no" id="gwdNo">${esc(opts.cancel||'Back')}</button>
          <button class="go ${opts.danger?'danger':''}" id="gwdGo">${esc(opts.confirm||'Confirm')}</button>
        </div></div>`;
      document.body.appendChild(ov);
      requestAnimationFrame(()=>ov.classList.add('on'));
      const inp = ov.querySelector('#gwdIn');
      if(inp){ inp.focus(); if(!multiline) inp.setSelectionRange(inp.value.length, inp.value.length); }
      function close(val){
        ov.classList.remove('on');
        setTimeout(()=>{ ov.remove(); resolve(val); }, 180);
      }
      ov.querySelector('#gwdGo').onclick = ()=>{ try{ navigator.vibrate && navigator.vibrate(12); }catch(e){}
        close(withInput ? (inp.value ?? '') : true); };
      ov.querySelector('#gwdNo').onclick = ()=> close(withInput ? null : false);
      ov.addEventListener('click', e => { if(e.target === ov) close(withInput ? null : false); });
      if(inp && !multiline) inp.addEventListener('keydown', e => { if(e.key === 'Enter') close(inp.value ?? ''); });
      document.addEventListener('keydown', function esch(e){
        if(e.key === 'Escape'){ close(withInput ? null : false); document.removeEventListener('keydown', esch); }
      });
    });
  }

  window.gwPrompt = opts => sheet(opts, true);
  window.gwConfirm = opts => sheet(opts, false);
  window.gwToast = (msg, ok=true) => {
    try{ if(!ok && navigator.vibrate) navigator.vibrate([30,40,30]); }catch(e){}
    const t = document.createElement('div');
    t.className = 'gwt' + (ok ? '' : ' bad');
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(()=>t.classList.add('on'));
    setTimeout(()=>{ t.classList.remove('on'); setTimeout(()=>t.remove(), 250); }, 2400);
  };
})();

/* ===== SCROLL RESTORATION (v1.5) =====
   Founder: "when I go back to a page, it goes straight to the top... I'd love
   to be exactly where I was, for fluidity."

   Root cause: our pages load content ASYNCHRONOUSLY (menu items, merchant
   list, order history all arrive via fetch, after first paint). The browser's
   native back/forward scroll restoration fires against the page's height AT
   THAT MOMENT — if the async content hasn't rendered yet, the page is still
   short, the saved scroll target doesn't exist, and it silently snaps to top.
   This is a classic SPA failure mode, not a browser bug.

   Fix: save scroll position ourselves (throttled, per-path, in sessionStorage
   — survives back/forward but not a fresh tab, which is the right scope).
   On load, poll document height until it stops growing (content has settled)
   before restoring — so we're never restoring against a page that's still
   shorter than where the customer actually was. */
(function(){
  try{ if('scrollRestoration' in history) history.scrollRestoration = 'manual'; }catch(e){}
  const KEY = 'gw_scroll:' + location.pathname + location.search;
  let saveT = null;
  function save(){
    clearTimeout(saveT);
    saveT = setTimeout(() => {
      try{ sessionStorage.setItem(KEY, String(window.scrollY)); }catch(e){}
    }, 120);
  }
  window.addEventListener('scroll', save, {passive: true});
  window.addEventListener('pagehide', () => {
    try{ sessionStorage.setItem(KEY, String(window.scrollY)); }catch(e){}
  });

  let target = 0;
  try{ target = parseInt(sessionStorage.getItem(KEY) || '0', 10) || 0; }catch(e){}
  if(!target) return;

  let lastHeight = -1, stableFrames = 0;
  const MAX_FRAMES = 90;   // ~1.5s ceiling — never hang waiting for content that won't come
  let frames = 0;
  function tryRestore(){
    frames++;
    const h = document.documentElement.scrollHeight;
    if(h === lastHeight) stableFrames++; else stableFrames = 0;
    lastHeight = h;
    // Height has held steady for 3 frames AND is tall enough to reach the
    // target, OR we've hit the ceiling — restore with whatever we've got.
    if((stableFrames >= 3 && h >= target + window.innerHeight * 0.5) || frames >= MAX_FRAMES){
      window.scrollTo({top: target, behavior: 'instant'});
      return;
    }
    requestAnimationFrame(tryRestore);
  }
  requestAnimationFrame(tryRestore);
})();

/* ===== NAV ACTIVE STATE (v1.5) =====
   Founder: "the activity button is messed up." Root cause: each page's bottom
   nav was static HTML with the "on" class hand-baked in — home.html always
   showed Home as active, and every OTHER page (support, courier, lead pages)
   ALSO showed Home as active because that markup was copy-pasted from
   home.html without updating which tab should really be lit. me.html had the
   opposite bug: nothing was marked active at all.

   Fix: compute it once, from wherever the customer actually is, instead of
   trusting whatever got baked into that page's copy. */
(function(){
  const links = document.querySelectorAll('.gw-nav .gw-navin > a');
  if(!links.length) return;
  const path = location.pathname;
  links.forEach(a => a.classList.remove('on'));
  let match = null;
  if(path === '/') match = links[0];
  else if(path.startsWith('/order') || path.startsWith('/courier')) match = links[1];
  else if(path.startsWith('/track/')) match = links[2];
  else if(path.startsWith('/me')) match = links[3];
  if(match) match.classList.add('on');
})();
