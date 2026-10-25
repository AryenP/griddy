// "Open on phone" (Aryen, Sun 05:45: "qr code option directly built into the website"): the operator's join QR from
// GET /api/join-qr, the same link `make qr` prints. The route answers this Mac only, so on a phone the button stays
// hidden. The code carries the join token: it is fetched when the dialog opens and dropped when it closes.
(() => {
  const btn = document.getElementById("phone-qr"), dlg = document.getElementById("qr-dialog");
  const box = document.getElementById("qr-code"), base = document.getElementById("qr-base");
  if (!btn || !dlg) return;

  async function load() {
    const r = await fetch("/api/join-qr?page=operator", { cache: "no-store" });
    if (r.ok) return r.json();
    const detail = (await r.json().catch(() => ({}))).detail;
    return { status: r.status, error: detail || `HTTP ${r.status}` };
  }

  // shown on this Mac only: 200, or 409 when PUBLIC_URL is not an address a phone can open (the dialog says why)
  load().then((d) => { btn.hidden = !(d.svg || d.status === 409); }).catch(() => {});

  btn.addEventListener("click", async () => {
    const d = await load().catch(() => ({ error: "the runtime is not answering" }));
    if (d.svg) {
      const img = new Image();                        // an image, not markup: only common.js's setHTML writes HTML
      img.alt = "QR code that opens the operator console on a phone";
      img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(d.svg);
      box.replaceChildren(img);
      base.textContent = `opens ${d.base}${d.page}`;
    } else {
      box.replaceChildren();
      base.textContent = `no code: ${d.error}`;
    }
    dlg.showModal();
  });
  dlg.addEventListener("close", () => { box.replaceChildren(); base.textContent = ""; });
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });   // a click on the backdrop closes it
})();
