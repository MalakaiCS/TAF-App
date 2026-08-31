// Supabase Edge Function: po-upload
//
// Serves the phone page staff use to photograph a purchase order and send it
// to the office. Photos land in the private `po-inbox` bucket (see
// migrate_po_inbox.sql) and the desktop app picks them up, reads them and
// clears them.
//
// Pairing: the desktop app shows a QR code containing this URL plus ?p=<id>.
// Scanning it links the phone to that PC, and the id travels with every batch
// so photos go back to the machine that asked for them rather than to
// whichever office PC happens to sweep first.
//
// This function must be deployed with JWT verification OFF, because it serves
// a plain web page that has to load *before* anyone can sign in. That is safe:
// the page is only HTML and JavaScript. Everything it does afterwards runs as
// the person who signs in, and Storage row-level security decides what they
// may actually do. No key beyond the public anon key is ever sent to it.
//
// Deploy:
//   supabase functions deploy po-upload --no-verify-jwt
// (dashboard: deploy it, then turn "Verify JWT" off in the function settings)

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY") ?? "";

// The body is encoded to UTF-8 bytes explicitly and the markup below is kept
// pure ASCII (HTML entities instead of literal punctuation and emoji), so the
// page still reads correctly even if something downstream serves it with the
// wrong charset.
const ENCODER = new TextEncoder();

Deno.serve(() => {
  return new Response(ENCODER.encode(page()), {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
});

function page(): string {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#1B3A5C">
<title>TAF &middot; Send Purchase Order</title>
<link rel="apple-touch-icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect width='100' height='100' fill='%231B3A5C'/%3E%3Ctext x='50' y='68' font-size='54' font-family='sans-serif' font-weight='bold' fill='white' text-anchor='middle'%3ET%3C/text%3E%3C/svg%3E">
<style>
  :root {
    --navy:#1B3A5C; --blue:#2E6DA4; --bg:#F4F6F8; --card:#FFFFFF;
    --text:#1F2933; --muted:#6B7A8C; --line:#DCE3EA;
    --green:#1E8E5A; --red:#C0392B; --amber:#8A6D00;
  }
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  body {
    margin:0; background:var(--bg); color:var(--text);
    font:16px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    padding-bottom:env(safe-area-inset-bottom);
  }
  header {
    background:var(--navy); color:#fff; padding:16px 18px;
    padding-top:calc(16px + env(safe-area-inset-top));
  }
  header h1 { margin:0; font-size:18px; }
  header p  { margin:3px 0 0; font-size:13px; color:#A9CCE3; }
  main { padding:16px; max-width:640px; margin:0 auto; }
  .card {
    background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:16px; margin-bottom:14px;
  }
  label { display:block; font-size:13px; font-weight:600; color:var(--muted);
          margin-bottom:5px; text-transform:uppercase; letter-spacing:.02em; }
  input[type=email], input[type=password], textarea {
    width:100%; padding:13px; font-size:16px; border:1px solid var(--line);
    border-radius:9px; background:#fff; color:var(--text); font-family:inherit;
  }
  textarea { resize:vertical; min-height:64px; }
  .field { margin-bottom:12px; }
  button {
    width:100%; padding:15px; font-size:16px; font-weight:700; color:#fff;
    background:var(--blue); border:0; border-radius:10px; cursor:pointer;
  }
  button.ghost { background:#fff; color:var(--blue); border:1.5px solid var(--blue); }
  button:disabled { opacity:.55; }
  button + button { margin-top:9px; }
  .msg { padding:11px 13px; border-radius:9px; font-size:14px; margin-bottom:12px; display:none; }
  .msg.err  { background:#FDECEC; color:var(--red);   display:block; }
  .msg.ok   { background:#E7F6EE; color:var(--green); display:block; }
  .pill {
    display:inline-block; background:#E7F6EE; color:var(--green);
    border-radius:20px; padding:4px 11px; font-size:12px; font-weight:700;
    margin-bottom:12px;
  }
  .shots { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin:12px 0 0; }
  .shot { position:relative; aspect-ratio:3/4; border-radius:9px; overflow:hidden;
          border:1px solid var(--line); background:#000; }
  .shot img { width:100%; height:100%; object-fit:cover; display:block; }
  .shot button {
    position:absolute; top:4px; right:4px; width:26px; height:26px; padding:0;
    border-radius:50%; background:rgba(0,0,0,.62); font-size:15px; line-height:1;
  }
  .shot span { position:absolute; bottom:0; left:0; padding:2px 6px; font-size:11px;
               background:rgba(0,0,0,.55); color:#fff; border-radius:0 8px 0 0; }
  .row { display:flex; align-items:center; justify-content:space-between; gap:10px; }
  .muted { color:var(--muted); font-size:13px; }
  a.signout { color:#A9CCE3; font-size:13px; text-decoration:underline; }
  .hide { display:none !important; }
  progress { width:100%; height:9px; margin-top:12px; }
</style>
</head>
<body>
<header>
  <div class="row">
    <div>
      <h1>Send Purchase Order</h1>
      <p id="sub">Total Air Filtration</p>
    </div>
    <a href="#" id="signout" class="signout hide">Sign out</a>
  </div>
</header>

<main>
  <div id="msg" class="msg"></div>
  <div id="pair" class="pill hide"></div>

  <section id="loginCard" class="card">
    <div class="field">
      <label for="email">Email</label>
      <input id="email" type="email" autocomplete="username"
             inputmode="email" autocapitalize="off" spellcheck="false">
    </div>
    <div class="field">
      <label for="pw">Password</label>
      <input id="pw" type="password" autocomplete="current-password">
    </div>
    <button id="loginBtn">Sign in</button>
    <p class="muted" style="margin:11px 0 0">
      Use the same login as the TAF Order Entry app.
    </p>
  </section>

  <section id="sendCard" class="card hide">
    <button id="shootBtn">&#128247; &nbsp;Take a photo</button>
    <button id="pickBtn" class="ghost">Choose from library</button>
    <input id="camera" type="file" accept="image/*" capture="environment" multiple class="hide">
    <input id="library" type="file" accept="image/*" multiple class="hide">

    <div id="shots" class="shots"></div>

    <div class="field hide" id="noteField" style="margin-top:14px">
      <label for="note">Note for the office (optional)</label>
      <textarea id="note" placeholder="e.g. urgent, or two separate orders on page 2"></textarea>
    </div>

    <button id="sendBtn" class="hide" style="margin-top:12px">Send to office</button>
    <progress id="bar" class="hide" max="100" value="0"></progress>
    <p class="muted" id="hint" style="margin:12px 0 0">
      Photograph every page. Fill the frame with the page, keep it flat and in
      focus, and avoid shadows across the numbers.
    </p>
  </section>
</main>

<script type="module">
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = ${JSON.stringify(SUPABASE_URL)};
const ANON_KEY     = ${JSON.stringify(ANON_KEY)};
const sb = createClient(SUPABASE_URL, ANON_KEY);

const $ = (id) => document.getElementById(id);
const shots = [];   // {file, url}

// ---- Pairing -----------------------------------------------------------
// ?p=<id> comes from the QR code the desktop app shows. Remember it so the
// page keeps working from a home-screen shortcut, which has no query string.
const params    = new URLSearchParams(location.search);
const pairId    = params.get("p")  || localStorage.getItem("taf_pair_id")    || "";
const pairLabel = params.get("n")  || localStorage.getItem("taf_pair_label") || "";
if (params.get("p")) {
  localStorage.setItem("taf_pair_id", params.get("p"));
  localStorage.setItem("taf_pair_label", params.get("n") || "");
}
if (pairId) {
  $("pair").textContent = "Linked to " + (pairLabel || "the office PC");
  $("pair").classList.remove("hide");
}

function say(text, kind) {
  const m = $("msg");
  m.textContent = text;
  m.className = "msg" + (kind ? " " + kind : "");
  if (text) window.scrollTo({ top: 0, behavior: "smooth" });
}

// ---- Session -----------------------------------------------------------
async function refresh() {
  const { data } = await sb.auth.getSession();
  const signedIn = !!data.session;
  $("loginCard").classList.toggle("hide", signedIn);
  $("sendCard").classList.toggle("hide", !signedIn);
  $("signout").classList.toggle("hide", !signedIn);
  $("sub").textContent = signedIn ? data.session.user.email : "Total Air Filtration";
}

$("loginBtn").onclick = async () => {
  const email = $("email").value.trim();
  const pw    = $("pw").value;
  if (!email || !pw) { say("Enter your email and password.", "err"); return; }
  $("loginBtn").disabled = true;
  $("loginBtn").textContent = "Signing in...";
  const { error } = await sb.auth.signInWithPassword({ email, password: pw });
  $("loginBtn").disabled = false;
  $("loginBtn").textContent = "Sign in";
  if (error) { say(error.message, "err"); return; }
  $("pw").value = "";
  say("", "");
  refresh();
};

$("signout").onclick = async (e) => {
  e.preventDefault();
  await sb.auth.signOut();
  say("", "");
  refresh();
};

// ---- Photos ------------------------------------------------------------
$("shootBtn").onclick = () => $("camera").click();
$("pickBtn").onclick  = () => $("library").click();
for (const id of ["camera", "library"]) {
  $(id).onchange = (e) => {
    for (const f of e.target.files) shots.push({ file: f, url: URL.createObjectURL(f) });
    e.target.value = "";
    drawShots();
  };
}

function drawShots() {
  const wrap = $("shots");
  wrap.innerHTML = "";
  shots.forEach((s, i) => {
    const d = document.createElement("div");
    d.className = "shot";
    const img = document.createElement("img");
    img.src = s.url;
    const b = document.createElement("button");
    b.textContent = "\\u00d7";
    b.title = "Remove";
    b.onclick = () => { URL.revokeObjectURL(s.url); shots.splice(i, 1); drawShots(); };
    const n = document.createElement("span");
    n.textContent = i + 1;
    d.append(img, b, n);
    wrap.append(d);
  });
  const any = shots.length > 0;
  $("sendBtn").classList.toggle("hide", !any);
  $("noteField").classList.toggle("hide", !any);
  $("sendBtn").textContent =
    "Send " + shots.length + " photo" + (shots.length === 1 ? "" : "s") + " to office";
}

// ---- Send --------------------------------------------------------------
$("sendBtn").onclick = async () => {
  if (!shots.length) return;
  const { data: sess } = await sb.auth.getSession();
  if (!sess.session) { say("Your sign-in expired - sign in again.", "err"); refresh(); return; }

  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const batch = stamp + "-" + Math.random().toString(36).slice(2, 8);

  $("sendBtn").disabled = true;
  $("bar").classList.remove("hide");
  $("bar").value = 0;
  say("", "");

  const names = [];
  try {
    for (let i = 0; i < shots.length; i++) {
      const f    = shots[i].file;
      const ext  = (f.name.split(".").pop() || "jpg").toLowerCase().replace(/[^a-z0-9]/g, "");
      const name = String(i + 1).padStart(2, "0") + "." + (ext || "jpg");
      $("sendBtn").textContent = "Sending photo " + (i + 1) + " of " + shots.length + "...";
      const { error } = await sb.storage.from("po-inbox")
        .upload(batch + "/" + name, f, {
          contentType: f.type || "image/jpeg",
          upsert: true,
        });
      if (error) throw error;
      names.push(name);
      $("bar").value = Math.round(((i + 1) / (shots.length + 1)) * 100);
    }

    // Written last: the app only picks up a batch once this marker exists, so
    // it can never read a half-uploaded set of photos.
    const manifest = {
      photos:     names,
      note:       $("note").value.trim(),
      sent_by:    sess.session.user.email,
      sent_at:    new Date().toISOString(),
      pair_id:    pairId,
      pair_label: pairLabel,
    };
    const { error: mErr } = await sb.storage.from("po-inbox").upload(
      batch + "/_complete.json",
      new Blob([JSON.stringify(manifest)], { type: "application/json" }),
      { contentType: "application/json", upsert: true });
    if (mErr) throw mErr;
    $("bar").value = 100;

    for (const s of shots) URL.revokeObjectURL(s.url);
    shots.length = 0;
    $("note").value = "";
    drawShots();
    say("Sent. " + (pairLabel ? pairLabel : "The office app") +
        " will pick it up within a minute - you can close this page.", "ok");
  } catch (err) {
    say("Couldn't send: " + (err && err.message ? err.message : err) +
        (names.length ? "  (" + names.length + " photo(s) did upload - resend the rest.)" : ""),
        "err");
  } finally {
    $("sendBtn").disabled = false;
    $("bar").classList.add("hide");
    drawShots();
  }
};

refresh();
</script>
</body>
</html>`;
}
