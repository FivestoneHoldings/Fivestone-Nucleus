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
