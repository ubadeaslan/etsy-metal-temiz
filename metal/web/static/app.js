// Small helpers for the local panel: busy overlay, lightbox, copy buttons, counters,
// model lists and the room placement box editor. No framework, no build step.

document.addEventListener("submit", (e) => {
  const form = e.target;
  const text = form.dataset.busy;
  if (!text) return;
  document.getElementById("busy-text").textContent = text;
  document.getElementById("busy").hidden = false;
  form.querySelectorAll("button").forEach((b) => (b.disabled = true));
});
window.addEventListener("pageshow", () => {
  const busy = document.getElementById("busy");
  if (busy) busy.hidden = true;
});

// forms marked data-keep-scroll (image order, delete) come back to the same spot instead of the top
document.addEventListener("submit", (e) => {
  if (!e.target.matches("[data-keep-scroll]")) return;
  try { sessionStorage.setItem("keep-scroll", JSON.stringify({ path: location.pathname, y: window.scrollY })); } catch { /* private mode */ }
});
(() => {
  let saved = null;
  try {
    saved = JSON.parse(sessionStorage.getItem("keep-scroll") || "null");
    sessionStorage.removeItem("keep-scroll");
  } catch { return; }
  if (!saved || saved.path !== location.pathname || location.search.includes("err=")) return;
  const restore = () => window.scrollTo(0, saved.y);
  restore();
  window.addEventListener("load", restore, { once: true });
})();

document.addEventListener("click", (e) => {
  const img = e.target.closest("img[data-zoom]");
  if (img) {
    const box = document.createElement("div");
    box.id = "lightbox";
    box.innerHTML = `<img src="${img.dataset.zoom}">`;
    box.addEventListener("click", () => box.remove());
    document.body.appendChild(box);
    return;
  }
  const copy = e.target.closest("[data-copy]");
  if (copy) {
    const src = document.getElementById(copy.dataset.copy);
    navigator.clipboard.writeText(src.value ?? src.textContent).then(() => {
      const old = copy.textContent;
      copy.textContent = "Kopyalandı";
      setTimeout(() => (copy.textContent = old), 1200);
    });
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") document.getElementById("lightbox")?.remove();
});

// live counters: data-count="max" (characters) or data-count-tags="13"
function updateCounters() {
  document.querySelectorAll("[data-count]").forEach((el) => {
    const out = document.getElementById(el.id + "-n");
    if (!out) return;
    const max = +el.dataset.count;
    out.textContent = `${el.value.length}/${max}`;
    out.classList.toggle("bad", el.value.length > max);
  });
  document.querySelectorAll("[data-count-tags]").forEach((el) => {
    const out = document.getElementById(el.id + "-n");
    const tags = el.value.split(/[,\n]/).map((t) => t.trim()).filter(Boolean);
    const long = tags.filter((t) => t.length > 20).length;
    out.textContent = `${tags.length}/13` + (long ? ` · ${long} tag 20 karakteri aşıyor` : "");
    out.classList.toggle("bad", tags.length > 13 || long > 0);
  });
}
document.addEventListener("input", updateCounters);
document.addEventListener("DOMContentLoaded", updateCounters);

// settings: fetch model lists into datalists
document.querySelectorAll("[data-models]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const p = btn.dataset.models;
    const status = document.getElementById(`models-${p}-status`);
    status.textContent = "Getiriliyor…";
    try {
      const res = await fetch(`/api/modeller/${p}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.status);
      for (const kind of ["image", "text"]) {
        const list = document.getElementById(`dl-${p}-${kind}`);
        list.innerHTML = data[kind].map((m) => `<option value="${m}">`).join("");
      }
      status.textContent = `Bağlantı tamam: ${data.image.length} görsel, ${data.text.length} metin modeli. Alana tıklayıp listeden seç.`;
    } catch (err) {
      status.textContent = "Hata: " + err.message;
    }
  });
});

// rooms: drag a rectangle on the photo to set where the design hangs
document.querySelectorAll(".room .stage").forEach((stage) => {
  const boxEl = stage.querySelector(".box");
  const id = stage.dataset.room;
  let start = null;
  const rel = (e) => {
    const r = stage.getBoundingClientRect();
    return [Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1), Math.min(Math.max((e.clientY - r.top) / r.height, 0), 1)];
  };
  // listing images are square: shade what the square crop (centred on the box, like mockup.room_background) drops
  const [cropA, cropB] = stage.querySelectorAll(".crop");
  const shade = (b) => {
    const [W, H] = JSON.parse(stage.dataset.size || "[1, 1]");
    if (!cropA) return;
    if (W >= H) {
      const side = H / W, cx = (b[0] + b[2]) / 2;
      const left = Math.min(Math.max(cx - side / 2, 0), 1 - side);
      cropA.style.cssText = `left:0;top:0;bottom:0;width:${left * 100}%`;
      cropB.style.cssText = `right:0;top:0;bottom:0;width:${(1 - left - side) * 100}%`;
    } else {
      const side = W / H, cy = (b[1] + b[3]) / 2;
      const top = Math.min(Math.max(cy - side / 2, 0), 1 - side);
      cropA.style.cssText = `left:0;right:0;top:0;height:${top * 100}%`;
      cropB.style.cssText = `left:0;right:0;bottom:0;height:${(1 - top - side) * 100}%`;
    }
  };
  const draw = (b) => {
    boxEl.style.left = b[0] * 100 + "%";
    boxEl.style.top = b[1] * 100 + "%";
    boxEl.style.width = (b[2] - b[0]) * 100 + "%";
    boxEl.style.height = (b[3] - b[1]) * 100 + "%";
    shade(b);
  };
  draw(JSON.parse(stage.dataset.box));
  stage.addEventListener("mousedown", (e) => { start = rel(e); });
  window.addEventListener("mousemove", (e) => {
    if (!start) return;
    const p = rel(e);
    draw([Math.min(start[0], p[0]), Math.min(start[1], p[1]), Math.max(start[0], p[0]), Math.max(start[1], p[1])]);
  });
  window.addEventListener("mouseup", async (e) => {
    if (!start) return;
    const p = rel(e);
    const b = [Math.min(start[0], p[0]), Math.min(start[1], p[1]), Math.max(start[0], p[0]), Math.max(start[1], p[1])];
    start = null;
    const status = stage.parentElement.querySelector(".status");
    const body = new URLSearchParams({ x0: b[0], y0: b[1], x1: b[2], y1: b[3] });
    const res = await fetch(`/odalar/${id}/kutu`, { method: "POST", body });
    status.textContent = res.ok ? "Yerleşim kaydedildi" : "Kutu çok küçük — tekrar çiz";
    if (res.ok) stage.dataset.box = JSON.stringify(b); else draw(JSON.parse(stage.dataset.box));
  });
  stage.parentElement.querySelector(".reset-box")?.addEventListener("click", async () => {
    const status = stage.parentElement.querySelector(".status");
    const res = await fetch(`/odalar/${id}/sifirla`, { method: "POST" });
    if (!res.ok) { status.textContent = "Sıfırlanamadı"; return; }
    const { box } = await res.json();
    stage.dataset.box = JSON.stringify(box);
    draw(box);
    status.textContent = "Yerleşim sıfırlandı";
  });
});

// design page: colour -> rooms picker. Click a colour, then its rooms (black 2, gold 2, the rest 1).
// Picking past the limit replaces the oldest pick; clicking a picked room removes it.
document.querySelectorAll("form.plan").forEach((form) => {
  const plan = JSON.parse(form.dataset.plan || "{}");
  const tabs = [...form.querySelectorAll(".slot-tab")];
  const opts = [...form.querySelectorAll(".room-opt")];
  const note = form.querySelector(".plan-note");
  const swatch = Object.fromEntries(tabs.map((t) => [t.dataset.fin, t.querySelector(".sw").style.background]));
  const max = (fin) => +tabs.find((t) => t.dataset.fin === fin).dataset.max;
  let active = (tabs.find((t) => (plan[t.dataset.fin] || []).length < +t.dataset.max) || tabs[0])?.dataset.fin;
  const render = () => {
    let picked = 0, slots = 0;
    tabs.forEach((t) => {
      const fin = t.dataset.fin, n = (plan[fin] || []).length;
      picked += n;
      slots += max(fin);
      t.classList.toggle("on", fin === active);
      t.classList.toggle("full", n >= max(fin));
      t.querySelector(".cnt").textContent = `${n}/${max(fin)}`;
      form.querySelector(`input[name="oda_${fin}"]`).value = (plan[fin] || []).join(",");
    });
    opts.forEach((o) => {
      const id = o.dataset.room;
      o.classList.toggle("sel", (plan[active] || []).includes(id));
      o.querySelector(".marks").innerHTML = tabs
        .filter((t) => (plan[t.dataset.fin] || []).includes(id))
        .map((t) => `<i class="sw" style="background:${swatch[t.dataset.fin]}"></i>`).join("");
    });
    if (note) note.textContent = `${picked}/${slots} renk görseli seçili` + (picked < slots ? " — eksik renkler atlanır" : "");
  };
  tabs.forEach((t) => t.addEventListener("click", () => { active = t.dataset.fin; render(); }));
  opts.forEach((o) => o.addEventListener("click", () => {
    const list = (plan[active] ||= []);
    const i = list.indexOf(o.dataset.room);
    if (i >= 0) list.splice(i, 1);
    else {
      if (list.length >= max(active)) list.shift();
      list.push(o.dataset.room);
    }
    render();
  }));
  render();
});

// size table: width in inches or cm (the other fills in), height from the design's proportions,
// import from pasted text or a screenshot (read on this PC by Tesseract, see metal/sizes.py)
const r1 = (v) => Math.round(v * 10) / 10;
document.querySelectorAll(".size-editor").forEach((ed) => {
  const tbody = ed.querySelector("tbody");
  const aspect = parseFloat(ed.dataset.aspect) || 0;
  const out = ed.querySelector(".import-out");
  const height = (row) => {
    const w = parseFloat(row.querySelector('input[name="sizes_in"]').value);
    const cell = row.querySelector(".h");
    if (!w) cell.textContent = "";
    else if (!aspect) cell.textContent = "kesim kontrolünden sonra";
    else {
      const h = r1(w * aspect); // same rounding as sizes.dims on the server
      cell.textContent = `${h} in / ${Math.round(h * 2.54)} cm`;
    }
  };
  const wire = (row) => {
    const inch = row.querySelector('input[name="sizes_in"]');
    const cm = row.querySelector(".cm");
    if (inch.value && !cm.value) cm.value = r1(inch.value * 2.54);
    inch.addEventListener("input", () => { cm.value = inch.value ? r1(inch.value * 2.54) : ""; height(row); });
    cm.addEventListener("input", () => { inch.value = cm.value ? Math.round((cm.value / 2.54) * 100) / 100 : ""; height(row); });
    row.querySelector(".del").addEventListener("click", () => row.remove());
    height(row);
  };
  const addRow = (width = "", note = "") => {
    const row = document.createElement("tr");
    row.innerHTML = '<td><input type="number" name="sizes_in" step="any" min="1" max="200"></td>'
      + '<td><input type="number" class="cm" step="any" min="2" max="508"></td><td class="h"></td>'
      + '<td><button type="button" class="small ghost del" title="Bu boyu sil">×</button></td>';
    if (width) row.querySelector('input[name="sizes_in"]').value = width;
    if (note) { row.classList.add("warn"); row.title = note; }
    tbody.appendChild(row);
    wire(row);
    return row;
  };
  tbody.querySelectorAll("tr").forEach(wire);
  ed.querySelector(".add").addEventListener("click", () => addRow().querySelector("input").focus());

  const apply = (data) => {
    if (data.error) { out.textContent = "Hata: " + data.error; return; }
    if (!data.rows.length) { out.textContent = "Bu metinde boy bulunamadı."; return; }
    tbody.innerHTML = "";
    data.rows.forEach((r) => addRow(r.w_in, r.note));
    const bad = data.rows.filter((r) => r.note).length;
    out.textContent = `${data.rows.length} boy tabloya alındı.` + (bad ? ` ${bad} satır sarı: üstüne gelip notu oku, kontrol et.` : "")
      + " Kaydetmeyi unutma.";
  };
  const send = async (url, payload) => {
    out.textContent = "Okunuyor…";
    try {
      const res = await fetch(url, { method: "POST", body: payload });
      apply(await res.json());
    } catch (err) {
      out.textContent = "Hata: " + err.message;
    }
  };
  ed.sendImage = (file) => {
    const fd = new FormData();
    fd.append("file", file);
    send("/api/boylar/oku", fd);
  };
  ed.querySelector(".parse").addEventListener("click", () => {
    const fd = new FormData();
    fd.append("text", ed.querySelector(".paste-text").value);
    send("/api/boylar/ayikla", fd);
  });
  ed.querySelector('.paste-zone input[type="file"]').addEventListener("change", (e) => {
    if (e.target.files[0]) ed.sendImage(e.target.files[0]);
  });
});
// the design page's size table: show when it has changes that are not saved yet, and stop another form
// (e.g. making the listing images) from reloading the page and dropping them without asking
(() => {
  const form = document.querySelector("[data-sizes-form]");
  if (!form) return;
  const snapshot = () => [...form.querySelectorAll('input[name="sizes_in"]')].map((i) => i.value).join("|");
  const saved = snapshot();
  const note = form.querySelector(".size-dirty");
  const dirty = () => snapshot() !== saved;
  const update = () => {
    note.hidden = !dirty();
    form.closest(".sizes-card")?.classList.toggle("dirty", dirty());
  };
  form.addEventListener("input", update);
  new MutationObserver(update).observe(form.querySelector("tbody"), { childList: true, subtree: true });
  // capture phase: runs before the busy overlay handler, so a "cancel" leaves the page as it was
  document.addEventListener("submit", (e) => {
    if (e.target === form || !dirty()) return;
    if (confirm("Boylarda kaydedilmemiş değişiklik var. Devam edersen bu değişiklikler kaybolur (görseller kayıtlı boylarla çıkar).\n\nÖnce \"Boyları kaydet\"e basmak için İptal'e bas.")) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    form.scrollIntoView({ behavior: "smooth", block: "start" });
  }, true);
})();

// a pasted screenshot goes to the size table whose import box has focus (or the only open one)
document.addEventListener("paste", (e) => {
  const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
  if (!item) return; // text pastes behave as usual
  const open = [...document.querySelectorAll(".size-import[open]")];
  const ed = e.target.closest?.(".size-editor") || (open.length === 1 ? open[0].closest(".size-editor") : null);
  if (!ed?.sendImage) return;
  e.preventDefault();
  ed.sendImage(item.getAsFile());
});
