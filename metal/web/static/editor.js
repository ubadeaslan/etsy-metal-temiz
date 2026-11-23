// Design editor. The hub-less cut mask as pixels (1 = metal) with tools to move floating parts, select
// and move or delete a region, paint and erase metal, and draw straight bridges. Undo/redo per action,
// zoom/pan, the original on a key press, and the server's cut check after every change.
// No framework, no build step.
(() => {
  "use strict";
  const root = document.getElementById("editor");
  if (!root) return;
  const cfg = JSON.parse(root.dataset.cfg);
  const W = cfg.w, H = cfg.h, N = W * H;
  const ppm = W / cfg.widthMm; // image pixels per mm
  const $ = (q) => root.querySelector(q);
  const view = $("canvas.view");
  const stage = $(".ed-stage");
  const ctx = view.getContext("2d");

  const METAL = [60, 64, 70], BG = [250, 249, 246];
  const ORDER = ["ADA", "KOPRU", "UC", "DELIK", "BOSLUK"];
  const COLORS = { ADA: "#e53935", KOPRU: "#e53935", UC: "#fb8c00", DELIK: "#1e88e5", BOSLUK: "#8e24aa" };
  const NAMES = { ADA: "Kopan parça", KOPRU: "İnce köprü", UC: "İnce uç", DELIK: "Küçük delik", BOSLUK: "Dar boşluk" };
  const PREFIX = { ADA: "P", KOPRU: "K", UC: "U", DELIK: "D", BOSLUK: "B" };
  const LABELS = { firca: "Fırça", silgi: "Silgi", kopru: "Köprü" };

  const mask = new Uint8Array(N);
  let orig = null; // the mask as opened
  const off = document.createElement("canvas");
  off.width = W; off.height = H;
  const offCtx = off.getContext("2d");
  const img = offCtx.createImageData(W, H);
  const origCanvas = document.createElement("canvas");
  origCanvas.width = W; origCanvas.height = H;

  // view: screen (device px) = image px * s + (ox, oy)
  let s = 1, ox = 0, oy = 0, fitScale = 1;
  const dpr = () => window.devicePixelRatio || 1;

  // ---------------------------------------------------------------- pixels -> picture
  function paint(x0, y0, x1, y1) {
    x0 = Math.max(0, x0 | 0); y0 = Math.max(0, y0 | 0); x1 = Math.min(W, Math.ceil(x1)); y1 = Math.min(H, Math.ceil(y1));
    if (x1 <= x0 || y1 <= y0) return;
    const d = img.data;
    for (let y = y0; y < y1; y++) {
      let i = y * W + x0, p = i * 4;
      for (let x = x0; x < x1; x++, i++, p += 4) {
        const c = mask[i] ? METAL : BG;
        d[p] = c[0]; d[p + 1] = c[1]; d[p + 2] = c[2]; d[p + 3] = 255;
      }
    }
    offCtx.putImageData(img, 0, 0, x0, y0, x1 - x0, y1 - y0);
  }
  let dirty = null;
  function touched(x, y) {
    if (!dirty) { dirty = [x, y, x + 1, y + 1]; return; }
    if (x < dirty[0]) dirty[0] = x;
    if (y < dirty[1]) dirty[1] = y;
    if (x >= dirty[2]) dirty[2] = x + 1;
    if (y >= dirty[3]) dirty[3] = y + 1;
  }
  function flush() {
    if (dirty) { paint(dirty[0], dirty[1], dirty[2], dirty[3]); dirty = null; }
    draw();
  }

  // ---------------------------------------------------------------- undo in 64 px tiles
  const T = 64, TX = Math.ceil(W / T);
  let op = null; // tile -> pixels before the running action
  const undoStack = [], redoStack = [];
  function tileRect(t) {
    const x0 = (t % TX) * T, y0 = Math.floor(t / TX) * T;
    return [x0, y0, Math.min(W, x0 + T), Math.min(H, y0 + T)];
  }
  function readTile(t) {
    const [x0, y0, x1, y1] = tileRect(t), w = x1 - x0, out = new Uint8Array(w * (y1 - y0));
    for (let y = y0; y < y1; y++) out.set(mask.subarray(y * W + x0, y * W + x1), (y - y0) * w);
    return out;
  }
  function writeTile(t, data) {
    const [x0, y0, x1, y1] = tileRect(t), w = x1 - x0;
    for (let y = y0; y < y1; y++) mask.set(data.subarray((y - y0) * w, (y - y0 + 1) * w), y * W + x0);
    paint(x0, y0, x1, y1);
  }
  function begin() { if (!op) op = new Map(); }
  function set(x, y, v) {
    if (x < 0 || y < 0 || x >= W || y >= H) return;
    const i = y * W + x;
    if (mask[i] === v) return;
    const t = Math.floor(y / T) * TX + Math.floor(x / T);
    if (!op.has(t)) op.set(t, readTile(t));
    mask[i] = v;
    touched(x, y);
  }
  function same(a, b) {
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
    return true;
  }
  function end(label) {
    if (!op) return false;
    const tiles = [];
    for (const [t, before] of op) {
      const after = readTile(t);
      if (!same(before, after)) tiles.push({ t, before, after });
    }
    op = null;
    flush();
    if (!tiles.length) return false;
    undoStack.push({ tiles, label });
    if (undoStack.length > 100) undoStack.shift();
    redoStack.length = 0;
    changed();
    return true;
  }
  function stepHistory(from, to, key, verb) {
    commitSelection();
    const entry = from.pop();
    if (!entry) { toast(key === "before" ? "Geri alınacak adım yok." : "İleri alınacak adım yok."); return; }
    for (const tile of entry.tiles) writeTile(tile.t, tile[key]);
    to.push(entry);
    draw();
    changed();
    toast(`${verb}: ${entry.label}`);
  }
  const undo = () => stepHistory(undoStack, redoStack, "before", "Geri alındı");
  const redo = () => stepHistory(redoStack, undoStack, "after", "Yinelendi");

  // ---------------------------------------------------------------- drawing shapes into the mask
  function capsule(a, b, r, v) {
    const [ax, ay] = a, [bx, by] = b;
    const x0 = Math.floor(Math.min(ax, bx) - r), x1 = Math.ceil(Math.max(ax, bx) + r);
    const y0 = Math.floor(Math.min(ay, by) - r), y1 = Math.ceil(Math.max(ay, by) + r);
    const dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy || 1e-9, r2 = r * r;
    for (let y = Math.max(0, y0); y <= Math.min(H - 1, y1); y++) {
      for (let x = Math.max(0, x0); x <= Math.min(W - 1, x1); x++) {
        let t = ((x + 0.5 - ax) * dx + (y + 0.5 - ay) * dy) / len2;
        t = t < 0 ? 0 : t > 1 ? 1 : t;
        const ex = ax + t * dx - x - 0.5, ey = ay + t * dy - y - 0.5;
        if (ex * ex + ey * ey <= r2) set(x, y, v);
      }
    }
  }

  // ---------------------------------------------------------------- floating selection
  // Selected metal is lifted off the mask (one open undo action) and drawn on top until it is dropped:
  // dropping stamps it at its new place and closes the action, so lift + move + drop is one undo step.
  let sel = null; // {x, y, w, h, bits, dx, dy, canvas}
  function lift(pixels) {
    let minx = W, miny = H, maxx = 0, maxy = 0;
    for (const i of pixels) {
      const x = i % W, y = (i / W) | 0;
      if (x < minx) minx = x; if (x > maxx) maxx = x;
      if (y < miny) miny = y; if (y > maxy) maxy = y;
    }
    const w = maxx - minx + 1, h = maxy - miny + 1, bits = new Uint8Array(w * h);
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const cc = c.getContext("2d"), im = cc.createImageData(w, h);
    begin();
    for (const i of pixels) {
      const x = i % W, y = (i / W) | 0, j = (y - miny) * w + (x - minx);
      bits[j] = 1;
      im.data[j * 4] = 32; im.data[j * 4 + 1] = 104; im.data[j * 4 + 2] = 200; im.data[j * 4 + 3] = 235;
      set(x, y, 0);
    }
    cc.putImageData(im, 0, 0);
    sel = { x: minx, y: miny, w, h, bits, dx: 0, dy: 0, canvas: c };
    flush();
  }
  function stamp(dx, dy) {
    for (let y = 0; y < sel.h; y++) {
      for (let x = 0; x < sel.w; x++) if (sel.bits[y * sel.w + x]) set(sel.x + dx + x, sel.y + dy + y, 1);
    }
  }
  function commitSelection() {
    if (!sel) return;
    const moved = sel.dx || sel.dy;
    stamp(sel.dx, sel.dy);
    sel = null;
    end(moved ? "Taşı" : "Seçim");
  }
  function cancelSelection() {
    if (!sel) return;
    stamp(0, 0);
    sel = null;
    end("Seçim");
  }
  function deleteSelection() {
    if (!sel) return;
    sel = null;
    end("Seçimi sil");
  }
  const inSelection = (p) => sel && p[0] >= sel.x + sel.dx && p[0] < sel.x + sel.dx + sel.w
    && p[1] >= sel.y + sel.dy && p[1] < sel.y + sel.dy + sel.h;

  function component(x0, y0) {
    // 4-connected metal part under the click; the main piece is refused (it would be most of the design)
    let metal = 0;
    for (let i = 0; i < N; i++) metal += mask[i];
    const limit = metal * 0.3, seen = new Uint8Array(N), stack = [y0 * W + x0], out = [];
    seen[stack[0]] = 1;
    while (stack.length) {
      const i = stack.pop();
      out.push(i);
      if (out.length > limit) return null;
      const x = i % W;
      if (x > 0 && mask[i - 1] && !seen[i - 1]) { seen[i - 1] = 1; stack.push(i - 1); }
      if (x < W - 1 && mask[i + 1] && !seen[i + 1]) { seen[i + 1] = 1; stack.push(i + 1); }
      if (i >= W && mask[i - W] && !seen[i - W]) { seen[i - W] = 1; stack.push(i - W); }
      if (i < N - W && mask[i + W] && !seen[i + W]) { seen[i + W] = 1; stack.push(i + W); }
    }
    return out;
  }

  let lasso = null;
  function finishLasso() {
    const pts = lasso;
    lasso = null;
    if (!pts || pts.length < 3) { draw(); return; }
    let minx = W, miny = H, maxx = 0, maxy = 0;
    for (const [x, y] of pts) {
      minx = Math.min(minx, Math.floor(x)); maxx = Math.max(maxx, Math.ceil(x));
      miny = Math.min(miny, Math.floor(y)); maxy = Math.max(maxy, Math.ceil(y));
    }
    minx = Math.max(0, minx); miny = Math.max(0, miny); maxx = Math.min(W - 1, maxx); maxy = Math.min(H - 1, maxy);
    const w = maxx - minx + 1, h = maxy - miny + 1;
    if (w < 2 || h < 2) { draw(); return; }
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const cc = c.getContext("2d");
    cc.beginPath();
    pts.forEach(([x, y], k) => (k ? cc.lineTo(x - minx, y - miny) : cc.moveTo(x - minx, y - miny)));
    cc.closePath();
    cc.fill();
    const a = cc.getImageData(0, 0, w, h).data, picked = [];
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = (y + miny) * W + x + minx;
        if (a[(y * w + x) * 4 + 3] > 127 && mask[i]) picked.push(i);
      }
    }
    if (!picked.length) { toast("Çevrilen alanda metal yok."); draw(); return; }
    lift(picked);
    toast("Seçildi: sürükleyerek taşı, Delete ile sil, Enter ile bırak.");
  }

  // ---------------------------------------------------------------- tools
  let tool = "tasi";
  const sizes = { firca: Math.max(4, cfg.minWidth + 1), silgi: Math.max(3, cfg.minGap + 1), kopru: Math.max(4, cfg.minWidth + 1) };
  const minSize = { firca: cfg.minWidth, silgi: cfg.minGap, kopru: cfg.minWidth };
  const sizeInput = $(".size"), sizeHint = $(".size-hint");
  const SIZE_HINTS = {
    firca: `Metal en az ${cfg.minWidth} mm (atölyenin en ince köprü sınırı).`,
    silgi: `Boşluk en az ${cfg.minGap} mm (en dar boşluk sınırı).`,
    kopru: `Köprü en az ${cfg.minWidth} mm.`,
    tasi: "Kopan bir parçaya tıkla, sürükle. Ok tuşları 1 mm (Shift ile 1 piksel).",
    sec: "Bölgeyi çevir; sürükle, Delete ile sil, Enter ile bırak.",
  };
  let bridgeA = null;
  function setTool(t) {
    commitSelection();
    bridgeA = null; lasso = null;
    tool = t;
    root.querySelectorAll(".tool").forEach((b) => b.classList.toggle("on", b.dataset.tool === t));
    const sized = t in sizes;
    sizeInput.disabled = !sized;
    sizeInput.value = sized ? sizes[t] : "";
    sizeHint.textContent = SIZE_HINTS[t];
    setCursor();
    draw();
  }
  function setCursor() {
    view.style.cursor = tool === "firca" || tool === "silgi" ? "none" : tool === "tasi" ? "default" : "crosshair";
  }
  sizeInput.addEventListener("change", () => {
    if (!(tool in sizes)) return;
    let v = parseFloat(String(sizeInput.value).replace(",", "."));
    if (!(v > 0)) v = sizes[tool];
    if (v < minSize[tool]) { v = minSize[tool]; toast(`${minSize[tool]} mm'den ince olamaz.`); }
    sizes[tool] = Math.min(v, 200);
    sizeInput.value = sizes[tool];
    draw();
  });
  root.querySelectorAll(".tool").forEach((b) => b.addEventListener("click", () => setTool(b.dataset.tool)));

  // ---------------------------------------------------------------- view
  function resize() {
    const r = stage.getBoundingClientRect(), k = dpr();
    const cx = (view.width / 2 - ox) / s, cy = (view.height / 2 - oy) / s;
    view.width = Math.max(1, Math.round(r.width * k));
    view.height = Math.max(1, Math.round(r.height * k));
    fitScale = Math.min(view.width / W, view.height / H) * 0.94;
    if (orig) { ox = view.width / 2 - cx * s; oy = view.height / 2 - cy * s; }
    draw();
  }
  function fit() {
    s = fitScale;
    ox = (view.width - W * s) / 2;
    oy = (view.height - H * s) / 2;
    draw();
  }
  function focusOn(y, x, zoom = 5) {
    s = Math.min(fitScale * zoom, 10 * dpr());
    ox = view.width / 2 - (x + 0.5) * s;
    oy = view.height / 2 - (y + 0.5) * s;
    draw();
  }
  function zoomAt(mx, my, f) {
    const ns = Math.min(Math.max(s * f, fitScale * 0.5), 24 * dpr());
    ox = mx - (mx - ox) * (ns / s);
    oy = my - (my - oy) * (ns / s);
    s = ns;
    draw();
  }
  const toImage = (e) => {
    const r = view.getBoundingClientRect(), k = dpr();
    return [((e.clientX - r.left) * k - ox) / s, ((e.clientY - r.top) * k - oy) / s];
  };
  const toScreen = (x, y) => [x * s + ox, y * s + oy];

  let showOrig = false, showProblems = true, layer = null, layerStale = false, marks = [], mouse = null;
  function circle(x, y, r, color, width, dash) {
    ctx.beginPath();
    ctx.setLineDash(dash || []);
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.arc(x, y, Math.max(r, 1), 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
  }
  function draw() {
    const k = dpr();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = "#e9e5de";
    ctx.fillRect(0, 0, view.width, view.height);
    if (!orig) return;
    ctx.setTransform(s, 0, 0, s, ox, oy);
    ctx.imageSmoothingEnabled = s < 1;
    ctx.drawImage(showOrig ? origCanvas : off, 0, 0);
    if (!showOrig) {
      if (layer && showProblems) { ctx.globalAlpha = layerStale ? 0.35 : 0.9; ctx.drawImage(layer, 0, 0); ctx.globalAlpha = 1; }
      if (sel) ctx.drawImage(sel.canvas, sel.x + sel.dx, sel.y + sel.dy);
    }
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    if (cfg.hub) {
      const [hx, hy] = toScreen(cfg.hub.cx + 0.5, cfg.hub.cy + 0.5);
      circle(hx, hy, cfg.hub.r * s, "rgba(40,120,60,.9)", 1.5 * k, [6 * k, 5 * k]);
      circle(hx, hy, cfg.hub.hole * s, "rgba(40,120,60,.9)", 1.5 * k);
    }
    if (showProblems && !showOrig && !layerStale) {
      for (const m of marks) {
        const [x0, y0] = toScreen(m.x0, m.y0), [x1, y1] = toScreen(m.x1, m.y1);
        circle((x0 + x1) / 2, (y0 + y1) / 2, Math.max(x1 - x0, y1 - y0) / 2 + 8 * k, COLORS[m.code], 2 * k);
      }
    }
    if (sel && !showOrig) {
      const [x0, y0] = toScreen(sel.x + sel.dx, sel.y + sel.dy);
      ctx.setLineDash([5 * k, 4 * k]);
      ctx.strokeStyle = "#2068c8";
      ctx.lineWidth = 1.2 * k;
      ctx.strokeRect(x0 - 2 * k, y0 - 2 * k, sel.w * s + 4 * k, sel.h * s + 4 * k);
      ctx.setLineDash([]);
    }
    if (lasso && lasso.length > 1) {
      ctx.beginPath();
      lasso.forEach(([x, y], i) => { const [a, b] = toScreen(x, y); i ? ctx.lineTo(a, b) : ctx.moveTo(a, b); });
      ctx.setLineDash([5 * k, 4 * k]);
      ctx.strokeStyle = "#2068c8";
      ctx.lineWidth = 1.5 * k;
      ctx.stroke();
      ctx.setLineDash([]);
    }
    if (tool === "kopru" && bridgeA && mouse) {
      const [ax, ay] = toScreen(...bridgeA), [bx, by] = toScreen(...mouse);
      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.lineTo(bx, by);
      ctx.strokeStyle = "rgba(46,160,67,.75)";
      ctx.lineWidth = Math.max(2, sizes.kopru * ppm * s);
      ctx.lineCap = "round";
      ctx.stroke();
      ctx.lineCap = "butt";
    }
    if ((tool === "firca" || tool === "silgi" || tool === "kopru") && mouse) {
      const [mx, my] = toScreen(...mouse);
      circle(mx, my, sizes[tool] * ppm * s / 2, tool === "silgi" ? "#b3261e" : "#2e7d4f", 1.5 * k, tool === "silgi" ? [4 * k, 3 * k] : null);
    }
    hud();
  }
  const hudZoom = $(".zoom"), hudPos = $(".pos"), hudScale = $(".scale");
  function hud() {
    hudZoom.textContent = `%${Math.round((s / dpr()) * 100)}`;
    hudPos.textContent = mouse && mouse[0] >= 0 && mouse[1] >= 0 && mouse[0] < W && mouse[1] < H
      ? `${(mouse[0] / ppm).toFixed(0)} × ${(mouse[1] / ppm).toFixed(0)} mm` : "";
    const cm = (10 * ppm * s) / dpr();
    hudScale.innerHTML = cm >= 6 ? `<i style="display:inline-block;width:${Math.min(cm, 400)}px;height:3px;background:#23221f;vertical-align:middle"></i> 1 cm` : "";
  }

  // ---------------------------------------------------------------- pointer
  let drag = null, space = false;
  view.addEventListener("contextmenu", (e) => e.preventDefault());
  view.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = view.getBoundingClientRect(), k = dpr();
    zoomAt((e.clientX - r.left) * k, (e.clientY - r.top) * k, Math.exp(-e.deltaY * 0.0015));
  }, { passive: false });
  view.addEventListener("pointerdown", (e) => {
    if (!orig) return;
    view.setPointerCapture(e.pointerId);
    const p = toImage(e);
    if (e.button === 1 || e.button === 2 || space) { drag = { kind: "pan", x: e.clientX, y: e.clientY }; return; }
    if (e.button !== 0) return;
    if (tool === "firca" || tool === "silgi") {
      commitSelection();
      begin();
      const r = (sizes[tool] * ppm) / 2, v = tool === "firca" ? 1 : 0;
      capsule(p, p, r, v);
      flush();
      drag = { kind: "paint", last: p, r, v };
      return;
    }
    if (tool === "kopru") {
      commitSelection();
      if (!bridgeA) { bridgeA = p; toast("Köprünün ikinci ucuna tıkla (Esc: vazgeç)."); draw(); return; }
      begin();
      capsule(bridgeA, p, (sizes.kopru * ppm) / 2, 1);
      bridgeA = null;
      end("Köprü");
      return;
    }
    if (sel && inSelection(p)) { drag = { kind: "move", sx: p[0], sy: p[1], dx: sel.dx, dy: sel.dy }; return; }
    commitSelection();
    if (tool === "sec") { lasso = [p]; drag = { kind: "lasso" }; return; }
    const x = Math.floor(p[0]), y = Math.floor(p[1]);
    if (x < 0 || y < 0 || x >= W || y >= H || !mask[y * W + x]) { draw(); return; }
    const part = component(x, y);
    if (!part) { toast("Ana gövde bütün olarak taşınamaz: taşımak istediğin bölgeyi Seç aracıyla çevir."); return; }
    lift(part);
    drag = { kind: "move", sx: p[0], sy: p[1], dx: 0, dy: 0 };
  });
  view.addEventListener("pointermove", (e) => {
    const p = toImage(e);
    mouse = p;
    if (!drag) {
      if (tool === "tasi") view.style.cursor = sel && inSelection(p) ? "move" : "default";
      draw();
      return;
    }
    if (drag.kind === "pan") {
      const k = dpr();
      ox += (e.clientX - drag.x) * k;
      oy += (e.clientY - drag.y) * k;
      drag.x = e.clientX; drag.y = e.clientY;
      draw();
    } else if (drag.kind === "paint") {
      capsule(drag.last, p, drag.r, drag.v);
      drag.last = p;
      flush();
    } else if (drag.kind === "move") {
      sel.dx = drag.dx + Math.round(p[0] - drag.sx);
      sel.dy = drag.dy + Math.round(p[1] - drag.sy);
      draw();
    } else if (drag.kind === "lasso") {
      const q = lasso[lasso.length - 1];
      if (Math.hypot(p[0] - q[0], p[1] - q[1]) * s > 3) lasso.push(p);
      draw();
    }
  });
  const release = () => {
    if (!drag) return;
    const kind = drag.kind;
    drag = null;
    if (kind === "paint") end(LABELS[tool]);
    else if (kind === "lasso") finishLasso();
    else if (kind === "move") { changed(); draw(); }
  };
  view.addEventListener("pointerup", release);
  view.addEventListener("pointercancel", release);
  view.addEventListener("pointerleave", () => { mouse = null; draw(); });

  // ---------------------------------------------------------------- keys and buttons
  const TOOL_KEYS = { v: "tasi", l: "sec", b: "firca", e: "silgi", k: "kopru" };
  document.addEventListener("keydown", (e) => {
    if (e.target.closest?.("input, textarea, select")) return;
    const key = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && key === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
    if ((e.ctrlKey || e.metaKey) && key === "y") { e.preventDefault(); redo(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === " ") { e.preventDefault(); space = true; view.style.cursor = "grab"; return; }
    if (sel && e.key.startsWith("Arrow")) {
      e.preventDefault();
      const step = e.shiftKey ? 1 : Math.max(1, Math.round(ppm));
      if (e.key === "ArrowLeft") sel.dx -= step;
      if (e.key === "ArrowRight") sel.dx += step;
      if (e.key === "ArrowUp") sel.dy -= step;
      if (e.key === "ArrowDown") sel.dy += step;
      changed();
      draw();
      return;
    }
    if (e.key === "Enter") { commitSelection(); return; }
    if (e.key === "Escape") {
      if (bridgeA) bridgeA = null;
      else if (lasso) lasso = null;
      else cancelSelection();
      draw();
      return;
    }
    if ((e.key === "Delete" || e.key === "Backspace") && sel) { e.preventDefault(); deleteSelection(); return; }
    if (TOOL_KEYS[key]) { setTool(TOOL_KEYS[key]); return; }
    if (key === "f") fit();
    if (key === "o" && !showOrig) { showOrig = true; draw(); }
  });
  document.addEventListener("keyup", (e) => {
    if (e.key === " ") { space = false; setCursor(); }
    if (e.key.toLowerCase() === "o") { showOrig = false; draw(); }
  });
  $(".undo").addEventListener("click", undo);
  $(".redo").addEventListener("click", redo);
  $(".fit").addEventListener("click", fit);
  const before = $(".before");
  before.addEventListener("pointerdown", () => { showOrig = true; draw(); });
  ["pointerup", "pointerleave"].forEach((ev) => before.addEventListener(ev, () => { showOrig = false; draw(); }));
  $(".show-problems").addEventListener("change", (e) => { showProblems = e.target.checked; draw(); });

  const msg = $(".ed-msg");
  let msgTimer = null;
  function toast(text) {
    msg.textContent = text;
    msg.classList.add("show");
    clearTimeout(msgTimer);
    msgTimer = setTimeout(() => msg.classList.remove("show"), 2600);
  }

  // ---------------------------------------------------------------- live cut check
  function packBits() {
    const out = new Uint8Array((N + 7) >> 3);
    for (let i = 0; i < N; i++) if (mask[i]) out[i >> 3] |= 128 >> (i & 7);
    if (sel) {
      for (let y = 0; y < sel.h; y++) {
        for (let x = 0; x < sel.w; x++) {
          if (!sel.bits[y * sel.w + x]) continue;
          const X = sel.x + sel.dx + x, Y = sel.y + sel.dy + y;
          if (X >= 0 && Y >= 0 && X < W && Y < H) { const i = Y * W + X; out[i >> 3] |= 128 >> (i & 7); }
        }
      }
    }
    return out;
  }
  const statusEl = $(".status"), countsEl = $(".counts"), marksEl = $(".marks"), findingsEl = $(".ed-findings");
  let checkTimer = null, inflight = false, again = false, edited = false;
  function changed() {
    edited = true;
    layerStale = true;
    statusEl.textContent = "Değişti, kontrol bekliyor…";
    clearTimeout(checkTimer);
    checkTimer = setTimeout(runCheck, 650);
  }
  async function runCheck() {
    if (inflight) { again = true; return; }
    inflight = true;
    statusEl.textContent = "Kontrol ediliyor…";
    try {
      const res = await fetch(`/t/${cfg.id}/duzenle/kontrol?w=${W}&h=${H}`, {
        method: "POST", body: packBits(), headers: { "Content-Type": "application/octet-stream" },
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.status);
      if (!again) showCheck(data); // a newer change is waiting: skip this stale result
    } catch (err) {
      statusEl.textContent = "Kontrol yapılamadı: " + err.message;
    }
    inflight = false;
    if (again) { again = false; runCheck(); }
  }
  function showCheck(data) {
    const counted = {};
    marks = data.marks.map(([code, y0, x0, y1, x1]) => ({ code, y0, x0, y1, x1 }))
      .sort((a, b) => ORDER.indexOf(a.code) - ORDER.indexOf(b.code) || a.y0 - b.y0 || a.x0 - b.x0)
      .map((m) => ({ ...m, label: PREFIX[m.code] + (counted[m.code] = (counted[m.code] || 0) + 1) }));
    statusEl.innerHTML = data.ok ? '<span class="tag ok">Kesime uygun</span>' : '<span class="tag err">HATA var</span>';
    countsEl.innerHTML = ORDER.filter((c) => counted[c]).map((c) =>
      `<li><i style="background:${COLORS[c]}"></i>${NAMES[c]}: <b>${counted[c]}</b></li>`).join("")
      || '<li class="muted">İşaretli sorun yok.</li>';
    marksEl.innerHTML = "";
    marks.slice(0, 120).forEach((m) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = m.label;
      b.style.borderLeftColor = COLORS[m.code];
      b.title = NAMES[m.code] + " — yakınlaştır";
      b.addEventListener("click", () => focusOn((m.y0 + m.y1) / 2, (m.x0 + m.x1) / 2, 6));
      marksEl.appendChild(b);
    });
    findingsEl.innerHTML = data.findings.map((f) =>
      `<li><span class="tag ${f.level}">${f.level}</span><span>${f.msg.replace(/</g, "&lt;")}</span></li>`).join("");
    if (data.layer) {
      const im = new Image();
      im.onload = () => { layer = im; layerStale = false; draw(); };
      im.src = data.layer;
    } else { layer = null; layerStale = false; draw(); }
  }

  // ---------------------------------------------------------------- save / leave
  let saving = false;
  const differs = () => {
    if (sel && (sel.dx || sel.dy)) return true;
    for (let i = 0; i < N; i++) if (mask[i] !== orig[i]) return true;
    return false;
  };
  $(".save-btn").addEventListener("click", async () => {
    if (!orig) return;
    commitSelection();
    if (!differs()) { toast("Değişiklik yok."); return; }
    saving = true;
    document.getElementById("busy-text").textContent = "Kaydediliyor, kontrol yenileniyor…";
    document.getElementById("busy").hidden = false;
    try {
      const res = await fetch(`/t/${cfg.id}/duzenle/kaydet?w=${W}&h=${H}`, {
        method: "POST", body: packBits(), headers: { "Content-Type": "application/octet-stream" },
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.status);
      location.href = data.url;
    } catch (err) {
      saving = false;
      document.getElementById("busy").hidden = true;
      toast("Kaydedilemedi: " + err.message);
    }
  });
  window.addEventListener("beforeunload", (e) => {
    if (!saving && orig && edited && differs()) { e.preventDefault(); e.returnValue = ""; }
  });

  // ---------------------------------------------------------------- start
  async function load() {
    try {
      const res = await fetch(`/t/${cfg.id}/duzenle/maske.png`, { cache: "no-store" });
      if (!res.ok) throw new Error((await res.json()).error || res.status);
      const bmp = await createImageBitmap(await res.blob());
      if (bmp.width !== W || bmp.height !== H) throw new Error("ölçü tutmuyor, sayfayı yenile");
      const c = document.createElement("canvas");
      c.width = W; c.height = H;
      const cc = c.getContext("2d", { willReadFrequently: true });
      cc.drawImage(bmp, 0, 0);
      const d = cc.getImageData(0, 0, W, H).data;
      for (let i = 0; i < N; i++) mask[i] = d[i * 4] < 128 ? 1 : 0;
    } catch (err) {
      statusEl.textContent = "Tasarım yüklenemedi: " + err.message;
      return;
    }
    orig = mask.slice();
    paint(0, 0, W, H);
    origCanvas.getContext("2d").drawImage(off, 0, 0);
    resize();
    if (cfg.focus) focusOn(cfg.focus[0], cfg.focus[1]); else fit();
    runCheck();
  }
  new ResizeObserver(resize).observe(stage);
  setTool("tasi");
  load();
})();
