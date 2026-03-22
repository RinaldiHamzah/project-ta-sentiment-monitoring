// small helper JS shared across pages
window.app = {
  fetchJSON: async function(url, opts) {
    const r = await fetch(url, opts);
    if(!r.ok) throw new Error("HTTP "+r.status);
    return r.json();
  }
};
