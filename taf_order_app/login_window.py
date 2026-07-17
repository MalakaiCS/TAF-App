"""
Login / Register / Reset-Password window for TAF Order App.

v2.0.0 rebrand — split-panel layout (brand-gradient panel + white form),
light/dark toggle, show/hide password, remember-me.  Backend auth logic is
unchanged from the previous version.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import messagebox
import threading
import queue
import json
import sys
import os
from pathlib import Path

# ── Theme palettes ──────────────────────────────────────────────────────────
LIGHT = {
    "panel1": "#0E2A3A", "panel2": "#1DA1E6",        # brand-gradient panel
    "form":   "#FFFFFF", "text":  "#0F1A24", "muted": "#5C6B78",
    "field":  "#F4F8FA", "border": "#DCE4EA", "accent": "#1DA1E6",
    "btn":    "#1DA1E6", "btnh":  "#1791CF", "link":  "#1187C9",
    "err":    "#E5484D", "ok":    "#09A659", "toggle": "#EDF1F4",
}
DARK = {
    "panel1": "#0A1F2B", "panel2": "#1591D1",
    "form":   "#13242F", "text":  "#EAF1F6", "muted": "#8FA0AC",
    "field":  "#0F2029", "border": "#243540", "accent": "#1DA1E6",
    "btn":    "#1DA1E6", "btnh":  "#38B0EE", "link":  "#5FC0F0",
    "err":    "#E5484D", "ok":    "#09A659", "toggle": "#0C1A24",
}


def _font_family() -> str:
    """Public Sans if it registered (main app loads it before login), else Segoe UI."""
    try:
        import tkinter.font as _tkf
        if "Public Sans" in _tkf.families():
            return "Public Sans"
    except Exception:
        pass
    return "Segoe UI"


FAM = _font_family()


def _dk(c: str, n: int = 20) -> str:
    h = c.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"#{max(0,r-n):02X}{max(0,g-n):02X}{max(0,b-n):02X}"


def _rgb(c: str):
    h = c.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _draw_gradient(canvas, w, h, c1, c2):
    """Vertical gradient from c1 (top) to c2 (bottom)."""
    r1, g1, b1 = _rgb(c1)
    r2, g2, b2 = _rgb(c2)
    for i in range(h):
        t = i / max(1, h - 1)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        canvas.create_line(0, i, w, i, fill=f"#{r:02x}{g:02x}{b:02x}")


def _resource(name: str) -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent
    return base / name


def _settings_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("APPDATA", Path.home())) / "TAF Order Entry"
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "settings.json"


def _load_remember() -> tuple[str, bool]:
    """Return (remembered_email, remember_flag)."""
    try:
        p = _settings_path()
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            remember = bool(d.get("remember_me", True))
            return (d.get("remember_email", "") if remember else "", remember)
    except Exception:
        pass
    return ("", True)


def _save_remember(email: str, remember: bool) -> None:
    try:
        p = _settings_path()
        d = {}
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
        d["remember_me"]    = bool(remember)
        d["remember_email"] = email if remember else ""
        p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except Exception:
        pass


def _big_btn(parent, text, command, bg, fg="white", font=None) -> tk.Button:
    """Full-width primary action button with hover-darken."""
    b = tk.Button(
        parent, text=text, command=command,
        bg=bg, fg=fg, activebackground=_dk(bg, 18), activeforeground=fg,
        relief="flat", bd=0, font=font or (FAM, 10, "bold"),
        pady=11, cursor="hand2",
    )
    b.bind("<Enter>", lambda e: b.config(bg=_dk(bg, 18)))
    b.bind("<Leave>", lambda e: b.config(bg=bg))
    return b


def _field(parent, P, show=None) -> tuple[tk.Frame, tk.Entry]:
    """Themed entry with a brand focus border."""
    outer = tk.Frame(parent, bg=P["border"], bd=0)
    e = tk.Entry(
        outer, bg=P["field"], fg=P["text"], font=(FAM, 11),
        relief="flat", bd=10, insertbackground=P["text"], highlightthickness=0,
    )
    if show:
        e.config(show=show)
    e.pack(fill="x", padx=1, pady=1, ipady=6)
    e.bind("<FocusIn>",  lambda ev: outer.config(bg=P["accent"]))
    e.bind("<FocusOut>", lambda ev: outer.config(bg=P["border"]))
    return outer, e


# ═══════════════════════════════════════════════════════════════════════════════
# Login Window (split panel)
# ═══════════════════════════════════════════════════════════════════════════════

class LoginWindow(tk.Toplevel):
    """
    Modal login / register window.
    self.result = {"email": str}  on success, or None if closed.
    """

    W, H = 900, 560

    def __init__(self, master):
        super().__init__(master)
        self.title("TAF Order App — Sign In")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.result = None
        self._mode  = "login"          # "login" | "register"

        remembered, remember_flag = _load_remember()
        self._cache = {"login_email": remembered, "login_pw": "",
                       "reg_name": "", "reg_email": "", "reg_pw": "", "reg_pw2": ""}
        self._remember = tk.BooleanVar(value=remember_flag)
        self._show_pw  = False

        # Default to the app's saved dark-mode preference, else light.
        self._dark = False
        try:
            sp = _settings_path()
            if sp.exists():
                self._dark = bool(json.loads(sp.read_text(encoding="utf-8")).get("dark_mode", False))
        except Exception:
            pass

        self.configure(bg=LIGHT["form"])
        self._build()

        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{self.W}x{self.H}+{(sw-self.W)//2}+{(sh-self.H)//2}")
        self.lift()
        self.grab_set()
        self.focus_force()

    # ── Build / rebuild ─────────────────────────────────────────────────────

    def _P(self) -> dict:
        return DARK if self._dark else LIGHT

    def _build(self):
        P = self._P()
        self.configure(bg=P["form"])
        if getattr(self, "_outer", None):
            self._outer.destroy()
        self._outer = tk.Frame(self, bg=P["form"])
        self._outer.pack(fill="both", expand=True)

        self._build_brand_panel(P)
        self._build_form_panel(P)

    def _build_brand_panel(self, P):
        left = tk.Frame(self._outer, bg=P["panel1"], width=360, height=self.H)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        cv = tk.Canvas(left, width=360, height=self.H, highlightthickness=0, bd=0)
        cv.pack(fill="both", expand=True)
        _draw_gradient(cv, 360, self.H, P["panel1"], P["panel2"])

        # Logo (colour wordmark reads on the navy region near the top)
        try:
            p = _resource("TAF_logo_horizontal.png")
            if p.exists():
                raw = tk.PhotoImage(file=str(p))
                f = max(1, raw.width() // 250)
                img = raw.subsample(f, f)
                cv.create_image(44, 60, anchor="nw", image=img)
                cv._logo = img
        except Exception:
            cv.create_text(44, 70, anchor="nw", text="TAF", fill="white",
                           font=(FAM, 30, "bold"))

        cv.create_text(44, 250, anchor="nw", text="Breathe Cleaner.\nLive Better.",
                       fill="white", font=(FAM, 22, "bold"))
        cv.create_text(44, 360, anchor="nw",
                       text="Filter Order Entry &\nWorksheet Generator",
                       fill="#DCEAF4", font=(FAM, 11))

        try:
            from taf_order_app.updater import APP_VERSION
            cv.create_text(44, self.H - 36, anchor="nw", text=f"V{APP_VERSION}",
                           fill="#BBD3E4", font=(FAM, 9, "bold"))
        except Exception:
            pass

    def _build_form_panel(self, P):
        right = tk.Frame(self._outer, bg=P["form"])
        right.pack(side="left", fill="both", expand=True)

        # Theme toggle (top-right)
        top = tk.Frame(right, bg=P["form"])
        top.pack(fill="x", padx=24, pady=(16, 0))
        tg = tk.Label(top, text=("☀  Light" if self._dark else "☾  Dark"),
                      bg=P["toggle"], fg=P["muted"], font=(FAM, 8, "bold"),
                      padx=10, pady=5, cursor="hand2")
        tg.pack(side="right")
        tg.bind("<Button-1>", lambda e: self._toggle_theme())

        body = tk.Frame(right, bg=P["form"], padx=48)
        body.pack(fill="both", expand=True)
        inner = tk.Frame(body, bg=P["form"])
        inner.place(relx=0.5, rely=0.46, anchor="center")
        inner.configure(width=380)

        if self._mode == "login":
            self._build_login_form(inner, P)
        else:
            self._build_register_form(inner, P)

    # ── Login form ───────────────────────────────────────────────────────────

    def _build_login_form(self, f, P):
        tk.Label(f, text="Welcome back", bg=P["form"], fg=P["text"],
                 font=(FAM, 22, "bold")).pack(anchor="w")
        tk.Label(f, text="Sign in to Total Air Filtration", bg=P["form"],
                 fg=P["muted"], font=(FAM, 10)).pack(anchor="w", pady=(2, 22))

        tk.Label(f, text="Email or username", bg=P["form"], fg=P["muted"],
                 font=(FAM, 9, "bold"), anchor="w").pack(fill="x", pady=(0, 4))
        self._lf_email, self._login_email = _field(f, P)
        self._lf_email.pack(fill="x", pady=(0, 14), ipadx=140)
        self._login_email.insert(0, self._cache.get("login_email", ""))

        tk.Label(f, text="Password", bg=P["form"], fg=P["muted"],
                 font=(FAM, 9, "bold"), anchor="w").pack(fill="x", pady=(0, 4))
        pw_row = tk.Frame(f, bg=P["border"])
        pw_row.pack(fill="x", pady=(0, 6))
        pw_in = tk.Frame(pw_row, bg=P["field"])
        pw_in.pack(fill="x", padx=1, pady=1)
        self._login_pw = tk.Entry(pw_in, bg=P["field"], fg=P["text"], font=(FAM, 11),
                                  relief="flat", bd=10, insertbackground=P["text"],
                                  highlightthickness=0,
                                  show=("" if self._show_pw else "•"))
        self._login_pw.pack(side="left", fill="x", expand=True, ipady=6)
        self._login_pw.insert(0, self._cache.get("login_pw", ""))
        eye = tk.Label(pw_in, text=("🙈" if self._show_pw else "👁"), bg=P["field"],
                       fg=P["muted"], cursor="hand2", padx=10)
        eye.pack(side="right")
        eye.bind("<Button-1>", lambda e: self._toggle_pw())
        self._login_pw.bind("<FocusIn>",  lambda ev: pw_row.config(bg=P["accent"]))
        self._login_pw.bind("<FocusOut>", lambda ev: pw_row.config(bg=P["border"]))

        opts = tk.Frame(f, bg=P["form"])
        opts.pack(fill="x", pady=(0, 16))
        tk.Checkbutton(opts, text="Remember me", variable=self._remember,
                       bg=P["form"], fg=P["muted"], font=(FAM, 9),
                       selectcolor=P["field"], activebackground=P["form"],
                       activeforeground=P["text"], bd=0,
                       highlightthickness=0).pack(side="left")
        fp = tk.Label(opts, text="Forgot password?", bg=P["form"], fg=P["link"],
                      font=(FAM, 9), cursor="hand2")
        fp.pack(side="right")
        fp.bind("<Button-1>", lambda e: ResetPasswordDialog(self))

        self._login_status = tk.StringVar()
        self._login_status_lbl = tk.Label(f, textvariable=self._login_status,
                                          bg=P["form"], fg=P["err"], font=(FAM, 9),
                                          wraplength=360, justify="left")
        self._login_status_lbl.pack(fill="x", pady=(0, 8))

        self._login_btn = _big_btn(f, "Sign In", self._do_login, bg=P["btn"])
        self._login_btn.pack(fill="x", pady=(0, 18))

        row = tk.Frame(f, bg=P["form"])
        row.pack()
        tk.Label(row, text="New here?  ", bg=P["form"], fg=P["muted"],
                 font=(FAM, 9)).pack(side="left")
        ca = tk.Label(row, text="Create an account", bg=P["form"], fg=P["link"],
                      font=(FAM, 9, "bold"), cursor="hand2")
        ca.pack(side="left")
        ca.bind("<Button-1>", lambda e: self._switch_mode("register"))

        self._login_email.bind("<Return>", lambda e: self._login_pw.focus_set())
        self._login_pw.bind("<Return>",    lambda e: self._do_login())
        self._login_email.focus_set()

    # ── Register form ──────────────────────────────────────────────────────

    def _build_register_form(self, f, P):
        tk.Label(f, text="Create your account", bg=P["form"], fg=P["text"],
                 font=(FAM, 22, "bold")).pack(anchor="w")
        tk.Label(f, text="Join Total Air Filtration", bg=P["form"],
                 fg=P["muted"], font=(FAM, 10)).pack(anchor="w", pady=(2, 18))

        specs = [
            ("Full Name",        "_rf_name",  "_reg_name",  "reg_name",  None),
            ("Email address",    "_rf_email", "_reg_email", "reg_email", None),
            ("Password",         "_rf_pw",    "_reg_pw",    "reg_pw",    "•"),
            ("Confirm password", "_rf_pw2",   "_reg_pw2",   "reg_pw2",   "•"),
        ]
        for lbl, fattr, eattr, ckey, show in specs:
            tk.Label(f, text=lbl, bg=P["form"], fg=P["muted"], font=(FAM, 9, "bold"),
                     anchor="w").pack(fill="x", pady=(0, 4))
            frm, ent = _field(f, P, show=show)
            frm.pack(fill="x", pady=(0, 10), ipadx=140)
            ent.insert(0, self._cache.get(ckey, ""))
            setattr(self, fattr, frm)
            setattr(self, eattr, ent)

        self._reg_status = tk.StringVar()
        self._reg_status_lbl = tk.Label(f, textvariable=self._reg_status,
                                        bg=P["form"], fg=P["err"], font=(FAM, 9),
                                        wraplength=360, justify="left")
        self._reg_status_lbl.pack(fill="x", pady=(0, 6))

        self._reg_btn = _big_btn(f, "Create Account", self._do_register, bg=P["ok"])
        self._reg_btn.pack(fill="x", pady=(0, 14))

        row = tk.Frame(f, bg=P["form"])
        row.pack()
        tk.Label(row, text="Already have an account?  ", bg=P["form"],
                 fg=P["muted"], font=(FAM, 9)).pack(side="left")
        si = tk.Label(row, text="Sign in", bg=P["form"], fg=P["link"],
                      font=(FAM, 9, "bold"), cursor="hand2")
        si.pack(side="left")
        si.bind("<Button-1>", lambda e: self._switch_mode("login"))

        self._reg_name.bind("<Return>",  lambda e: self._reg_email.focus_set())
        self._reg_email.bind("<Return>", lambda e: self._reg_pw.focus_set())
        self._reg_pw.bind("<Return>",    lambda e: self._reg_pw2.focus_set())
        self._reg_pw2.bind("<Return>",   lambda e: self._do_register())
        self._reg_name.focus_set()

    # ── Theme / mode ─────────────────────────────────────────────────────────

    def _cache_fields(self):
        try:
            if self._mode == "login":
                self._cache["login_email"] = self._login_email.get()
                self._cache["login_pw"]    = self._login_pw.get()
            else:
                self._cache["reg_name"]  = self._reg_name.get()
                self._cache["reg_email"] = self._reg_email.get()
                self._cache["reg_pw"]    = self._reg_pw.get()
                self._cache["reg_pw2"]   = self._reg_pw2.get()
        except Exception:
            pass

    def _toggle_theme(self):
        self._cache_fields()
        self._dark = not self._dark
        self._build()

    def _toggle_pw(self):
        self._cache_fields()
        self._show_pw = not self._show_pw
        self._build()

    def _switch_mode(self, mode):
        self._cache_fields()
        self._mode = mode
        self._build()

    # ── Actions (unchanged backend logic) ────────────────────────────────────

    def _do_login(self):
        from taf_order_app import db
        email = self._login_email.get().strip()
        pw    = self._login_pw.get()
        if not email or not pw:
            self._login_status.set("Please enter your email and password.")
            return

        self._login_btn.config(state="disabled", text="Signing in…")
        self._login_status_lbl.config(fg=self._P()["muted"])
        self._login_status.set("Connecting to server…")
        self.update()

        q = queue.Queue()

        def _work():
            try:
                q.put(("status", "Verifying credentials…"))
                db.sign_in(email, pw)
                q.put(("status", "Loading profile…"))
                q.put(("success", None))
            except Exception as exc:
                msg = str(exc)
                if "Invalid login" in msg or "invalid_credentials" in msg.lower():
                    msg = "Incorrect email or password."
                elif "Email not confirmed" in msg:
                    msg = "Please confirm your email before signing in."
                q.put(("error", msg))

        def _poll():
            try:
                while True:
                    kind, data = q.get_nowait()
                    if kind == "status":
                        self._login_status.set(data)
                    elif kind == "success":
                        _save_remember(email, self._remember.get())
                        self._on_success()
                        return
                    elif kind == "error":
                        self._login_status.set(data)
                        self._login_status_lbl.config(fg=self._P()["err"])
                        self._login_btn.config(state="normal", text="Sign In")
                        return
            except queue.Empty:
                pass
            self.after(50, _poll)

        threading.Thread(target=_work, daemon=True).start()
        self.after(50, _poll)

    def _do_register(self):
        from taf_order_app import db
        name  = self._reg_name.get().strip()
        email = self._reg_email.get().strip()
        pw    = self._reg_pw.get()
        pw2   = self._reg_pw2.get()

        if not name or not email or not pw:
            self._reg_status.set("Please fill in all fields.")
            return
        if pw != pw2:
            self._reg_status.set("Passwords do not match.")
            return
        if len(pw) < 6:
            self._reg_status.set("Password must be at least 6 characters.")
            return

        self._reg_btn.config(state="disabled", text="Creating account…")
        self._reg_status_lbl.config(fg=self._P()["muted"])
        self._reg_status.set("Connecting…")
        self.update()

        q = queue.Queue()

        def _work():
            try:
                q.put(("status", "Creating account…"))
                user = db.sign_up(email, pw)
                if user and user.id:
                    if not db.current_user():
                        try:
                            q.put(("status", "Signing in…"))
                            db.sign_in(email, pw)
                        except Exception:
                            q.put(("info",
                                   "Account created! Confirm your email then sign in."))
                            return
                    q.put(("status", "Setting up profile…"))
                    username = db.generate_username(name)
                    db.create_profile(str(db.current_user().id), email, name, username)
                    q.put(("success", None))
                else:
                    q.put(("info", "Account created — confirm your email then sign in."))
            except Exception as exc:
                msg = str(exc)
                if "already registered" in msg.lower() or "already exists" in msg.lower():
                    msg = "An account with that email already exists."
                q.put(("error", msg))

        def _poll():
            try:
                while True:
                    kind, data = q.get_nowait()
                    if kind == "status":
                        self._reg_status.set(data)
                        self._reg_status_lbl.config(fg=self._P()["muted"])
                    elif kind == "success":
                        _save_remember(email, self._remember.get())
                        self._on_success()
                        return
                    elif kind == "info":
                        self._reg_status.set(data)
                        self._reg_status_lbl.config(fg=self._P()["ok"])
                        self._reg_btn.config(state="normal", text="Create Account")
                        return
                    elif kind == "error":
                        self._reg_status.set(data)
                        self._reg_status_lbl.config(fg=self._P()["err"])
                        self._reg_btn.config(state="normal", text="Create Account")
                        return
            except queue.Empty:
                pass
            self.after(50, _poll)

        threading.Thread(target=_work, daemon=True).start()
        self.after(50, _poll)

    def _on_success(self):
        from taf_order_app import db
        self.result = {"email": db.current_email()}
        self.grab_release()
        self.destroy()

    def _on_close(self):
        self.result = None
        self.grab_release()
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
# Reset-Password dialog (light brand)
# ═══════════════════════════════════════════════════════════════════════════════

class ResetPasswordDialog(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        P = LIGHT
        self.title("Reset Password")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.configure(bg=P["form"])

        wrap = tk.Frame(self, bg=P["form"], padx=36, pady=28)
        wrap.pack(fill="both", expand=True)

        tk.Label(wrap, text="Reset Password", bg=P["form"], fg=P["text"],
                 font=(FAM, 16, "bold")).pack(anchor="w", pady=(0, 4))
        tk.Label(wrap,
                 text="A reset link will be sent to your email.\n"
                      "If the link shows 'localhost', ask your admin to set the\n"
                      "Supabase Site URL, or to reset your password in User Management.",
                 bg=P["form"], fg=P["muted"], font=(FAM, 9),
                 justify="left").pack(anchor="w", pady=(0, 18))

        tk.Label(wrap, text="Email address", bg=P["form"], fg=P["muted"],
                 font=(FAM, 9, "bold"), anchor="w").pack(fill="x", pady=(0, 4))
        self._ef, self._email = _field(wrap, P)
        self._ef.pack(fill="x", pady=(0, 10))

        self._status = tk.StringVar()
        tk.Label(wrap, textvariable=self._status, bg=P["form"], fg=P["err"],
                 font=(FAM, 9), wraplength=320, justify="left").pack(fill="x", pady=(0, 10))

        btn_row = tk.Frame(wrap, bg=P["form"])
        btn_row.pack(fill="x")
        _big_btn(btn_row, "Send Reset Link", self._send, bg=P["btn"]).pack(fill="x", pady=(0, 8))
        _big_btn(btn_row, "Cancel", self.destroy, bg=P["muted"]).pack(fill="x")

        self.update_idletasks()
        W, H = 420, 320
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        self._email.focus_set()
        self._email.bind("<Return>", lambda e: self._send())

    def _send(self):
        from taf_order_app import db
        email = self._email.get().strip()
        if not email:
            self._status.set("Please enter your email address.")
            return
        self._status.set("Sending…")
        self.update()

        q = queue.Queue()

        def _work():
            try:
                db.reset_password_for_email(email)
                q.put(("done", None))
            except Exception as exc:
                q.put(("error", str(exc)))

        def _poll():
            try:
                while True:
                    kind, data = q.get_nowait()
                    if kind == "done":
                        messagebox.showinfo(
                            "Reset Link Sent",
                            "A password reset link has been sent.\n\n"
                            "Check your inbox and follow the link to set a new password.",
                            parent=self)
                        self.destroy()
                        return
                    elif kind == "error":
                        self._status.set(f"Error: {data}")
                        return
            except queue.Empty:
                pass
            self.after(50, _poll)

        threading.Thread(target=_work, daemon=True).start()
        self.after(50, _poll)


# ═══════════════════════════════════════════════════════════════════════════════
# First-run API key setup (light brand)
# ═══════════════════════════════════════════════════════════════════════════════

class ApiKeySetupDialog(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        P = LIGHT
        self.title("Database Setup")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.configure(bg=P["form"])
        self.result = None

        wrap = tk.Frame(self, bg=P["form"], padx=36, pady=28)
        wrap.pack(fill="both", expand=True)

        tk.Label(wrap, text="Database Setup", bg=P["form"], fg=P["text"],
                 font=(FAM, 16, "bold")).pack(anchor="w", pady=(0, 4))
        tk.Label(wrap,
                 text="Get the 'anon public' key from:\n"
                      "supabase.com → your project → Settings → API",
                 bg=P["form"], fg=P["muted"], font=(FAM, 9),
                 justify="left").pack(anchor="w", pady=(0, 16))

        tk.Label(wrap, text="Supabase Anon Key", bg=P["form"], fg=P["muted"],
                 font=(FAM, 9, "bold"), anchor="w").pack(fill="x", pady=(0, 4))
        self._kf, self._key_entry = _field(wrap, P)
        self._kf.pack(fill="x", pady=(0, 6))

        self._status = tk.StringVar()
        tk.Label(wrap, textvariable=self._status, bg=P["form"], fg=P["err"],
                 font=(FAM, 9), wraplength=380).pack(fill="x", pady=(0, 12))

        _big_btn(wrap, "Connect", self._connect, bg=P["btn"]).pack(fill="x", pady=(0, 8))
        _big_btn(wrap, "Skip (offline mode)", self._cancel, bg=P["muted"]).pack(fill="x")

        self.update_idletasks()
        W, H = 460, 320
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        self.grab_set()
        self._key_entry.focus_set()

    def _connect(self):
        from taf_order_app import db
        key = self._key_entry.get().strip()
        if not key:
            self._status.set("Please enter the API key.")
            return
        self._status.set("Connecting…")
        self.update()
        try:
            db.init(key)
            db.get_client().table("orders").select("id").limit(1).execute()
            self.result = key
            self.grab_release()
            self.destroy()
        except Exception as exc:
            self._status.set(f"Connection failed: {exc}")

    def _cancel(self):
        self.result = None
        self.grab_release()
        self.destroy()
