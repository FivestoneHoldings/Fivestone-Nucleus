/* GateWay device profile — lives ONLY on this device. Nothing harvested, nothing synced.
   The luxury the big apps can't offer: a profile that is actually yours. */
(function(){
  const KEY = 'gw_profile_v1';
  function load(){
    try{ return JSON.parse(localStorage.getItem(KEY)) || {}; }catch(e){ return {}; }
  }
  function save(p){
    try{ localStorage.setItem(KEY, JSON.stringify(p)); }catch(e){}
    return p;
  }
  window.gwProfile = {
    get: load,
    set(patch){ return save(Object.assign(load(), patch)); },
    addAddress(addr){
      const p = load(); p.addresses = p.addresses || [];
      addr = (addr||'').trim();
      if(addr && !p.addresses.includes(addr)){
        p.addresses.unshift(addr); p.addresses = p.addresses.slice(0,5);
      }
      return save(p);
    },
    removeAddress(addr){
      const p = load(); p.addresses = (p.addresses||[]).filter(a=>a!==addr);
      return save(p);
    },
    recordOrder(entry){
      const p = load(); p.history = p.history || [];
      if(entry.oid && !p.history.some(h=>h.oid===entry.oid)){
        p.history.unshift(entry); p.history = p.history.slice(0,40);
      }
      return save(p);
    },
    greeting(){
      const p = load(); if(!p.name) return '';
      const h = new Date().getHours();
      const part = h < 12 ? 'morning' : h < 17 ? 'afternoon' : 'evening';
      return 'Good ' + part + ', ' + p.name.split(' ')[0];
    },
    localImpactCents(){
      const p = load();
      return (p.history||[]).reduce((a,h)=>a + (parseInt(h.total_cents)||0), 0);
    }
  };
})();
