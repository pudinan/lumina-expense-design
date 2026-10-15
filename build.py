"""Inline the Lumina Expense design pages and their local dependencies into a
single index.html with a page switcher.

Usage: python3 -I build.py <project-folder> [output.html]

Each page is a standalone Design Component document (one <x-dc> per document),
so every page is built self-contained, embedded as inert text, and mounted into
its own srcdoc iframe when its tab is first opened.
"""
import base64, functools, hashlib, html as htmllib, json, re, subprocess, sys, tempfile
from pathlib import Path

src = Path(sys.argv[1]).expanduser()
out = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).with_name("index.html"))
DS = "_ds/terra-tdv-design-system-ab077799-082e-474d-9341-23824b43225a"

PAGES = [
    ("desktop", "Desktop", "Desktop.dc.html"),
    ("mobile", "Mobile", "Mobile.dc.html"),
    ("policy", "Employee expense policy", "Employee detail - expense policy.dc.html"),
]

# Marker used to keep "</script" inside embedded page text from closing the
# outer <script type="text/plain"> container; restored in the browser.
ESC = "<\\/__lm_script"
# "<!--" inside a <script> can switch the HTML parser into an escaped state
# that ignores the closing tag, so it is masked the same way.
ESC_COMMENT = "<\\!__lm_comment"


def script_safe(js: str) -> str:
    # Keep inline scripts from closing early, and keep the runtime's raw
    # template re-parse (it searches the page text for "<x-dc>") pointed at the real block.
    return js.replace("</script", "<\\/script").replace("<x-dc>", "\\u003cx-dc>")


def inline_script(rel: str) -> str:
    return "<script>\n" + script_safe((src / rel).read_text(encoding="utf-8")) + "\n</script>"


# After booting, the runtime re-reads its own page source with
# fetch(location.href) to get the unparsed template. Pages are mounted via
# iframe srcdoc (blob: frames are unreachable from file:// pages), where that
# fetch can't work, so the shell hands the source over on the frame element.
RAW_FETCH = 'fetch(location.href).then((res) => res.ok ? res.text() : "")'
RAW_FROM_SHELL = ('(window.frameElement && typeof window.frameElement.__lmRaw === "string" '
                  '? Promise.resolve(window.frameElement.__lmRaw) : ' + RAW_FETCH + ')')


def runtime_script() -> str:
    js = (src / "support.js").read_text(encoding="utf-8")
    if js.count(RAW_FETCH) != 1:
        raise SystemExit("support.js: expected exactly one self-fetch to patch")
    return "<script>\n" + script_safe(js.replace(RAW_FETCH, RAW_FROM_SHELL)) + "\n</script>"


# React/ReactDOM are embedded so pages don't need unpkg; the runtime skips its
# CDN load when window.React and window.ReactDOM already exist. The vendored
# files must match the SRI hashes the runtime itself would have enforced.
VENDOR = Path(__file__).with_name("vendor")


@functools.cache
def react_scripts() -> str:
    runtime = (src / "support.js").read_text(encoding="utf-8")
    tags = []
    for name, sri_var in (("react", "REACT_SRI"), ("react-dom", "REACT_DOM_SRI")):
        data = (VENDOR / f"{name}.production.min.js").read_bytes()
        expected = re.search(rf'var {sri_var} = "([^"]+)"', runtime).group(1)
        actual = "sha384-" + base64.b64encode(hashlib.sha384(data).digest()).decode()
        if actual != expected:
            raise SystemExit(f"vendor/{name}.production.min.js does not match {sri_var} in support.js")
        tags.append("<script>\n" + script_safe(data.decode("utf-8")) + "\n</script>")
    return "\n".join(tags)


@functools.cache
def logo_data_uri(rel: str) -> str:
    # Logos ship at ~3000px wide but render ~17px tall; downscale to 102px tall (6x).
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "logo.png"
        subprocess.run(["sips", "--resampleHeight", "102", str(src / rel), "--out", str(dst)],
                       check=True, capture_output=True)
        return "data:image/png;base64," + base64.b64encode(dst.read_bytes()).decode()


def build_page(filename: str) -> str:
    page = (src / filename).read_text(encoding="utf-8")

    def sub_once(pattern: str, repl: str) -> None:
        nonlocal page
        page, n = re.subn(pattern, lambda _: repl, page)
        if n != 1:
            raise SystemExit(f"{filename}: expected 1 match for {pattern!r}, got {n}")

    # The bundle tag sits inside <helmet>, which the runtime re-executes from its
    # text; inlined, that copy fails to parse. Load it once from <head> instead.
    sub_once(rf'<script src="{re.escape(DS)}/_ds_bundle\.js"></script>\n?', "")
    sub_once(r'<script src="\./support\.js"></script>',
             react_scripts() + "\n" + runtime_script() + "\n" + inline_script(f"{DS}/_ds_bundle.js"))

    # styles.css only @imports the token files, which are inlined individually.
    sub_once(rf'<link rel="stylesheet" href="{re.escape(DS)}/styles\.css">\n?', "")
    for name in ("fonts", "colors", "typography", "spacing"):
        css = (src / DS / "tokens" / f"{name}.css").read_text(encoding="utf-8")
        sub_once(rf'<link rel="stylesheet" href="{re.escape(DS)}/tokens/{name}\.css">', f"<style>\n{css}\n</style>")

    for variant in ("light", "dark"):
        rel = f"assets/terra-logo-{variant}.png"
        if f'src="{rel}"' in page:
            page = page.replace(f'src="{rel}"', f'src="{logo_data_uri(rel)}"')

    leftover = re.findall(r'(?:src|href)="(?!https?:|data:|#)[^"]+"', page)
    if leftover:
        raise SystemExit(f"{filename}: unresolved local references: {sorted(set(leftover))}")
    return page


embedded = []
for key, _, filename in PAGES:
    page = re.sub(r"</script", ESC, build_page(filename), flags=re.I).replace("<!--", ESC_COMMENT)
    if "<x-dc>" not in page:
        raise SystemExit(f"{filename}: no <x-dc> block")
    embedded.append(f'<script type="text/plain" id="page-{key}">{page}</script>')

# Figma-style panning: hold Space and drag, drag with the middle mouse button,
# or toggle the hand tool (H on, V off) so any left-drag pans. Runs from the
# shell against each same-origin page frame; a full-viewport overlay inside the
# frame takes the drag so the prototype's own controls don't react to it.
PAN_JS = r"""
  const handBtn = document.getElementById("hand");
  let handMode = false;
  let spaceHeld = false;
  const pans = new Set();

  const isEditable = (el) => !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));

  function refreshPan() {
    handBtn.setAttribute("aria-pressed", handMode);
    for (const p of pans) p.refresh();
  }
  function setHand(on) { handMode = on; refreshPan(); }
  function setSpace(on) { if (spaceHeld !== on) { spaceHeld = on; refreshPan(); } }

  function onKey(e) {
    // Ctrl/⌘ + = / - / 0 zoom the design instead of the whole browser page.
    if ((e.metaKey || e.ctrlKey) && !e.altKey && e.type === "keydown") {
      if (e.key === "=" || e.key === "+") step(1);
      else if (e.key === "-" || e.key === "_") step(-1);
      else if (e.key === "0") zoomAt(1);
      else return;
      e.preventDefault();
      return;
    }
    if (isEditable(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.code === "Space") {
      e.preventDefault();
      if (e.type === "keydown") { if (!e.repeat) setSpace(true); } else setSpace(false);
    } else if (e.type === "keydown" && !e.repeat) {
      if (e.key === "h" || e.key === "H") setHand(!handMode);
      else if (e.key === "v" || e.key === "V" || (e.key === "Escape" && handMode)) setHand(false);
    }
  }
  handBtn.addEventListener("click", () => setHand(!handMode));
  for (const t of ["keydown", "keyup"]) window.addEventListener(t, onKey, true);
  window.addEventListener("blur", () => setSpace(false));

  // Trackpad pinch arrives as a wheel event with ctrlKey set (Chrome, Edge,
  // Firefox); Ctrl/⌘ + mouse wheel looks the same. Safari sends gesture events.
  function onZoomWheel(e, x, y) {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    if (x == null) return; // over the shell bar: just block browser zoom
    const dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
    zoomAt(zoomOf[current] * Math.exp(-Math.max(-25, Math.min(25, dy)) * 0.01), x, y);
  }
  function bindGestures(win, coords) {
    let base = 1;
    win.addEventListener("wheel", (e) => onZoomWheel(e, ...coords(e)), { passive: false });
    win.addEventListener("gesturestart", (e) => { e.preventDefault(); base = zoomOf[current]; });
    win.addEventListener("gesturechange", (e) => {
      e.preventDefault();
      const [x, y] = coords(e);
      if (x != null) zoomAt(base * e.scale, x, y);
    });
    win.addEventListener("gestureend", (e) => e.preventDefault());
  }
  bindGestures(window, () => []);

  function attachPan(frame) {
    const win = frame.contentWindow, doc = frame.contentDocument;
    if (!doc || doc.__lmPan) return;
    doc.__lmPan = true;
    const scroller = () => doc.scrollingElement || doc.documentElement;
    const shield = doc.createElement("div");
    shield.style.cssText = "position:fixed;inset:0;z-index:2147483647;display:none;cursor:grab;touch-action:none;background:transparent";
    doc.documentElement.appendChild(shield);

    let drag = null;
    const pan = { refresh() { shield.style.display = handMode || spaceHeld || drag ? "block" : "none"; } };
    pans.add(pan);

    function start(e) {
      const s = scroller();
      drag = { id: e.pointerId, x: e.clientX, y: e.clientY, left: s.scrollLeft, top: s.scrollTop };
      pan.refresh();
      shield.style.cursor = "grabbing";
      try { shield.setPointerCapture(e.pointerId); } catch {}
      e.preventDefault();
    }
    function end(e) {
      if (!drag || e.pointerId !== drag.id) return;
      drag = null;
      shield.style.cursor = "grab";
      pan.refresh();
    }
    shield.addEventListener("pointerdown", (e) => { if (e.button === 0 || e.button === 1) start(e); });
    shield.addEventListener("pointermove", (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      scroller().scrollTo(drag.left - (e.clientX - drag.x), drag.top - (e.clientY - drag.y));
    });
    shield.addEventListener("pointerup", end);
    shield.addEventListener("pointercancel", end);
    // Middle-button drag works anywhere, without arming the hand tool first.
    doc.addEventListener("pointerdown", (e) => { if (e.button === 1 && e.target !== shield) start(e); }, true);
    doc.addEventListener("mousedown", (e) => { if (e.button === 1) e.preventDefault(); }, true);
    for (const t of ["keydown", "keyup"]) win.addEventListener(t, onKey, true);
    win.addEventListener("blur", () => setSpace(false));
    bindGestures(win, (e) => [e.clientX, e.clientY]);
    // In a srcdoc frame "#id" links resolve against the shell's URL and would
    // load the shell inside the frame; scroll to the target in place instead.
    doc.addEventListener("click", (e) => {
      const a = e.target.closest && e.target.closest('a[href^="#"]');
      if (!a) return;
      e.preventDefault();
      const id = decodeURIComponent(a.getAttribute("href").slice(1));
      const target = id && doc.getElementById(id);
      if (target) target.scrollIntoView({ block: "start" });
      else if (!id) scroller().scrollTo({ top: 0 });
    }, true);
    pan.refresh();
  }
"""

tabs = "\n".join(
    f'      <button type="button" role="tab" data-page="{k}" aria-controls="frame-{k}">{htmllib.escape(label)}</button>'
    for k, label, _ in PAGES
)
pages_json = json.dumps([k for k, _, _ in PAGES])
titles_json = json.dumps({k: label for k, label, _ in PAGES})

shell = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lumina Expense</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600&display=swap">
<style>
  :root {{
    --bar-h: 52px;
    --ink: #272428;
    --muted: #7a787c;
    --line: #d4d3d5;
    --surface: #ffffff;
    --page: #efeff0;
    --brand: #26587e;
    --brand-tint: #d5e9f4;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ height: 100%; margin: 0; }}
  body {{ background: var(--page); color: var(--ink); font: 400 14px/1.4 'Poppins', system-ui, sans-serif; display: flex; flex-direction: column; }}
  .bar {{ flex: 0 0 var(--bar-h); display: flex; align-items: center; gap: 16px; padding: 0 16px; background: var(--surface); border-bottom: 1px solid var(--line); }}
  .brand {{ font: 600 11px/1 'Poppins', sans-serif; letter-spacing: .08em; text-transform: uppercase; color: var(--brand); white-space: nowrap; }}
  .tabs {{ display: flex; gap: 4px; padding: 4px; background: var(--page); border-radius: 100px; overflow-x: auto; scrollbar-width: none; }}
  .tabs button {{ flex: none; height: 32px; padding: 0 14px; border: 0; border-radius: 100px; background: transparent; color: var(--muted); font: 500 13px/1 'Poppins', sans-serif; cursor: pointer; transition: background 150ms cubic-bezier(.4,0,.2,1), color 150ms cubic-bezier(.4,0,.2,1); }}
  .tabs button:hover {{ color: var(--ink); }}
  .tabs button[aria-selected="true"] {{ background: var(--surface); color: var(--brand); box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
  .tabs button:focus-visible {{ outline: 2px solid var(--brand); outline-offset: 2px; }}
  .tool {{ margin-left: auto; flex: none; display: flex; padding: 4px; background: var(--page); border-radius: 100px; }}
  .tool button {{ width: 32px; height: 32px; border: 0; border-radius: 100px; background: transparent; color: var(--muted); cursor: pointer; display: grid; place-items: center; }}
  .tool button:hover {{ color: var(--ink); background: var(--surface); }}
  .tool button[aria-pressed="true"] {{ background: var(--brand); color: #fff; }}
  .tool button:focus-visible {{ outline: 2px solid var(--brand); outline-offset: 2px; }}
  .zoom {{ display: flex; align-items: center; gap: 2px; padding: 4px; background: var(--page); border-radius: 100px; flex: none; }}
  .zoom button, .zoom select {{ height: 32px; border: 0; border-radius: 100px; background: transparent; color: var(--ink); font: 500 13px/1 'Poppins', sans-serif; cursor: pointer; }}
  .zoom button {{ width: 32px; font-size: 18px; }}
  .zoom button:hover:not(:disabled), .zoom select:hover {{ background: var(--surface); }}
  .zoom button:disabled {{ color: var(--line); cursor: default; }}
  .zoom select {{ padding: 0 8px; text-align: center; appearance: none; -webkit-appearance: none; min-width: 64px; }}
  .zoom :focus-visible {{ outline: 2px solid var(--brand); outline-offset: 2px; }}
  .frames {{ position: relative; flex: 1; min-height: 0; overflow: hidden; background: var(--page); }}
  /* Zoom renders the page at a larger viewport, then scales it down to fit. */
  .frames iframe {{ position: absolute; top: 0; left: 0; width: calc(100% / var(--z, 1)); height: calc(100% / var(--z, 1)); border: 0; background: var(--page); transform: scale(var(--z, 1)); transform-origin: 0 0; }}
  .frames iframe[hidden] {{ display: none; }}
  @media (max-width: 560px) {{ .brand {{ display: none; }} }}
</style>
</head>
<body>
  <header class="bar">
    <span class="brand">Lumina Expense</span>
    <nav class="tabs" role="tablist" aria-label="Pages">
{tabs}
    </nav>
    <div class="tool">
      <button type="button" id="hand" aria-pressed="false" aria-label="Hand tool" title="Hand tool (H) — drag to move around. Or hold Space, or drag with the middle mouse button.">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 11V6a2 2 0 0 0-4 0v5M14 10V4a2 2 0 0 0-4 0v6M10 10.5V6a2 2 0 0 0-4 0v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/></svg>
      </button>
    </div>
    <div class="zoom" role="group" aria-label="Zoom">
      <button type="button" id="zoom-out" aria-label="Zoom out" title="Zoom out">−</button>
      <select id="zoom-level" aria-label="Zoom level" title="Zoom level"></select>
      <button type="button" id="zoom-in" aria-label="Zoom in" title="Zoom in">+</button>
    </div>
  </header>
  <main class="frames" id="frames"></main>
{chr(10).join(embedded)}
<script>
(() => {{
  const PAGES = {pages_json};
  const TITLES = {titles_json};
  const ESC = {json.dumps(ESC)};
  const ESC_COMMENT = {json.dumps(ESC_COMMENT)};
  const frames = document.getElementById("frames");
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const mounted = {{}};
  let current = null;

  const LEVELS = [0.1, 0.25, 0.33, 0.5, 0.67, 0.75, 0.8, 0.9, 1, 1.25, 1.5, 2];
  const MIN_Z = LEVELS[0], MAX_Z = LEVELS[LEVELS.length - 1];
  const zoomOut = document.getElementById("zoom-out");
  const zoomIn = document.getElementById("zoom-in");
  const zoomLevel = document.getElementById("zoom-level");
  zoomLevel.innerHTML = `<option value="custom" hidden></option>` +
    LEVELS.map((z) => `<option value="${{z}}">${{Math.round(z * 100)}}%</option>`).join("");
  const zoomOf = {{}};
  try {{ Object.assign(zoomOf, JSON.parse(localStorage.getItem("lm-zoom") || "{{}}")); }} catch {{}}
  const clampZ = (z) => Math.min(MAX_Z, Math.max(MIN_Z, Number(z) || 1));

  function setZoom(z) {{
    z = clampZ(z);
    zoomOf[current] = z;
    try {{ localStorage.setItem("lm-zoom", JSON.stringify(zoomOf)); }} catch {{}}
    mounted[current].style.setProperty("--z", z);
    if (LEVELS.includes(z)) zoomLevel.value = String(z);
    else {{ zoomLevel.options[0].text = Math.round(z * 100) + "%"; zoomLevel.value = "custom"; }}
    zoomOut.disabled = z <= MIN_Z;
    zoomIn.disabled = z >= MAX_Z;
  }}

  // Zoom so the page point under (x, y) — the frame's own client coordinates —
  // stays under the pointer, like Figma. Omit x/y to zoom around the centre.
  function zoomAt(z2, x, y) {{
    const s = mounted[current].contentDocument?.scrollingElement;
    const z = zoomOf[current];
    z2 = clampZ(z2);
    if (!s) return setZoom(z2);
    if (x == null) {{ x = s.clientWidth / 2; y = s.clientHeight / 2; }}
    const px = s.scrollLeft + x, py = s.scrollTop + y;
    setZoom(z2);
    s.scrollLeft = px - x * z / z2;
    s.scrollTop = py - y * z / z2;
  }}
  function step(dir) {{
    const z = zoomOf[current];
    const next = dir > 0 ? LEVELS.find((l) => l > z + 1e-3) : [...LEVELS].reverse().find((l) => l < z - 1e-3);
    zoomAt(next ?? z);
  }}
  zoomOut.addEventListener("click", () => step(-1));
  zoomIn.addEventListener("click", () => step(1));
  zoomLevel.addEventListener("change", () => zoomAt(Number(zoomLevel.value)));

{PAN_JS}
  function mount(key) {{
    if (mounted[key]) return mounted[key];
    const text = document.getElementById("page-" + key).textContent
      .split(ESC).join("</script").split(ESC_COMMENT).join("<!--");
    const frame = document.createElement("iframe");
    frame.id = "frame-" + key;
    frame.title = TITLES[key];
    // srcdoc (not a blob: URL) so the frame stays reachable when index.html is
    // opened straight from disk; __lmRaw feeds the runtime's template re-read.
    frame.__lmRaw = text;
    frame.srcdoc = text;
    frame.addEventListener("load", () => attachPan(frame));
    frames.appendChild(frame);
    return (mounted[key] = frame);
  }}

  function show(key) {{
    if (!PAGES.includes(key)) key = PAGES[0];
    const frame = mount(key);
    for (const k in mounted) mounted[k].hidden = k !== key;
    current = key;
    setZoom(zoomOf[key] ?? 1);
    for (const t of tabs) {{
      const on = t.dataset.page === key;
      t.setAttribute("aria-selected", on);
      t.tabIndex = on ? 0 : -1;
    }}
    document.title = "Lumina Expense – " + TITLES[key];
    if (location.hash.slice(1) !== key) history.replaceState(null, "", "#" + key);
    return frame;
  }}

  for (const t of tabs) {{
    t.addEventListener("click", () => show(t.dataset.page));
    t.addEventListener("keydown", (e) => {{
      const dir = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (!dir) return;
      const next = tabs[(tabs.indexOf(t) + dir + tabs.length) % tabs.length];
      next.focus();
      show(next.dataset.page);
    }});
  }}
  window.addEventListener("hashchange", () => show(location.hash.slice(1)));
  show(location.hash.slice(1));
}})();
</script>
</body>
</html>
"""

out.write_text(shell, encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")
