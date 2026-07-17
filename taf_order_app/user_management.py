"""
User Management dialog — visible to Managers and above.
Managers can assign Employee role.
Admins/Directors can assign any role.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import queue

CA   = "#1A4F8A"
CBG  = "#EDF2F7"
CCA  = "#FFFFFF"
CTX  = "#2D3748"
CMU  = "#718096"
CSP  = "#CBD5E0"
CGR  = "#1E8449"
CRD  = "#C0392B"
CNE  = "#4A5568"
CRE  = "#EBF5FB"
CSL  = "#D6EAF8"
F_BODY = ("Segoe UI", 9)
F_BOLD = ("Segoe UI", 9, "bold")
F_SEC  = ("Segoe UI", 10, "bold")
F_SM   = ("Segoe UI", 8)
F_TTL  = ("Segoe UI", 12, "bold")

ROLE_COLOURS = {
    "Director": "#6C3483",
    "Admin":    "#1A4F8A",
    "Manager":  "#1E8449",
    "Employee": "#4A5568",
}

ALL_ROLES = ["Director", "Admin", "Manager", "Employee"]


def _dk(c: str, n: int = 22) -> str:
    h = c.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"#{max(0,r-n):02X}{max(0,g-n):02X}{max(0,b-n):02X}"


def _flat_btn(parent, text, command, bg=CA, fg="white",
              font=F_BOLD, pady=6, padx=12) -> tk.Button:
    b = tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                  activebackground=_dk(bg), activeforeground=fg,
                  relief="flat", bd=0, font=font, pady=pady, padx=padx,
                  cursor="hand2")
    b.bind("<Enter>", lambda e: b.config(bg=_dk(bg)))
    b.bind("<Leave>", lambda e: b.config(bg=bg))
    return b


class UserManagementDialog(tk.Toplevel):
    """Full user-management window."""

    def __init__(self, master):
        from taf_order_app import db
        self._db = db

        super().__init__(master)
        self.title("User Management")
        self.configure(bg=CBG)
        self.transient(master)
        self.grab_set()
        self.lift()
        self.focus_force()
        self.resizable(True, True)

        self._profiles: list = []
        self._build()
        self._load()

        self.update_idletasks()
        W, H = 700, 480
        px = master.winfo_rootx() + master.winfo_width()  // 2 - W // 2
        py = master.winfo_rooty() + master.winfo_height() // 2 - H // 2
        self.geometry(f"{W}x{H}+{px}+{py}")

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="User Management",
                 bg=CA, fg="white", font=F_TTL).pack(side="left")
        caller_role = self._db.current_role()
        tk.Label(hdr, text=f"Your role: {caller_role}",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(side="right")

        # Treeview
        tree_wrap = tk.Frame(self, bg=CCA,
                             highlightbackground=CSP, highlightthickness=1)
        tree_wrap.pack(fill="both", expand=True, padx=12, pady=(10, 0))
        tree_wrap.rowconfigure(0, weight=1)
        tree_wrap.columnconfigure(0, weight=1)

        style = ttk.Style(self)
        style.configure("UM.Treeview",
                        background=CCA, fieldbackground=CCA,
                        foreground=CTX, font=F_BODY, rowheight=26)
        style.configure("UM.Treeview.Heading",
                        background=CA, foreground="white",
                        font=F_BOLD, relief="flat")
        style.map("UM.Treeview",
                  background=[("selected", CSL)],
                  foreground=[("selected", CTX)])

        cols = ("username", "full_name", "email", "role")
        self.tree = ttk.Treeview(tree_wrap, columns=cols,
                                 show="headings", style="UM.Treeview",
                                 selectmode="browse")
        self.tree.grid(row=0, column=0, sticky="nsew")

        col_defs = {
            "username":  ("Username",    120, "w"),
            "full_name": ("Full Name",   170, "w"),
            "email":     ("Email",       210, "w"),
            "role":      ("Role",        100, "center"),
        }
        for col, (hd, wd, anc) in col_defs.items():
            self.tree.heading(col, text=hd)
            self.tree.column(col, width=wd, anchor=anc, minwidth=60)

        self.tree.tag_configure("even", background=CRE)
        self.tree.tag_configure("odd",  background=CCA)

        vsb = ttk.Scrollbar(tree_wrap, orient="vertical",
                            command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)

        # Footer
        foot = tk.Frame(self, bg=CBG, padx=12, pady=10)
        foot.pack(fill="x")

        _flat_btn(foot, "Refresh", self._load, bg=CNE, pady=8, padx=16).pack(side="left")
        _flat_btn(foot, "Change Role…", self._change_role,
                  bg=CA, pady=8, padx=16).pack(side="left", padx=(8, 0))

        # Directors/Admins only
        if self._db.role_level() >= 4:
            _flat_btn(foot, "Edit Profile…", self._edit_profile,
                      bg="#5D6D7E", pady=8, padx=16).pack(side="left", padx=(8, 0))
            _flat_btn(foot, "Delete User", self._delete_user,
                      bg=CRD, pady=8, padx=16).pack(side="left", padx=(8, 0))

        _flat_btn(foot, "+ Create User", self._create_user,
                  bg=CGR, pady=8, padx=16).pack(side="left", padx=(8, 0))

        self._status = tk.StringVar(value="Loading users…")
        tk.Label(foot, textvariable=self._status,
                 bg=CBG, fg=CMU, font=F_SM).pack(side="right")

    def _load(self):
        self._status.set("Loading…")
        self.update()

        q = queue.Queue()

        def _work():
            try:
                profiles = self._db.get_all_profiles()
                q.put(("ok", profiles))
            except Exception as exc:
                q.put(("error", str(exc)))

        def _poll():
            try:
                while True:
                    kind, data = q.get_nowait()
                    if kind == "ok":
                        self._populate(data)
                        return
                    elif kind == "error":
                        self._status.set(f"Error: {data}")
                        return
            except queue.Empty:
                pass
            self.after(50, _poll)

        threading.Thread(target=_work, daemon=True).start()
        self.after(50, _poll)

    def _populate(self, profiles: list):
        self._profiles = profiles
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for i, p in enumerate(profiles):
            tag = "even" if i % 2 == 0 else "odd"
            self.tree.insert("", "end", iid=str(i), tags=(tag,), values=(
                p.get("username", ""),
                p.get("full_name", ""),
                p.get("email", ""),
                p.get("role", "Employee"),
            ))
        self._status.set(f"{len(profiles)} user{'s' if len(profiles) != 1 else ''} loaded.")

    def _get_selected_profile(self) -> dict | None:
        sel = self.tree.selection()
        if not sel:
            return None
        return self._profiles[int(sel[0])]

    def _edit_profile(self):
        prof = self._get_selected_profile()
        if not prof:
            messagebox.showinfo("Edit Profile", "Select a user first.", parent=self)
            return
        if self._db.role_level() < 4:
            messagebox.showwarning("No Permission",
                                   "Only Directors and Admins can edit profiles.",
                                   parent=self)
            return
        EditProfileDialog(self, prof, self._db, on_done=self._load)

    def _delete_user(self):
        prof = self._get_selected_profile()
        if not prof:
            messagebox.showinfo("Delete User", "Select a user first.", parent=self)
            return
        if self._db.role_level() < 4:
            messagebox.showwarning("No Permission",
                                   "Only Directors and Admins can delete users.",
                                   parent=self)
            return
        # Prevent self-deletion
        if prof.get("id") == str(self._db.current_user().id):
            messagebox.showwarning("Cannot Delete",
                                   "You cannot delete your own account.",
                                   parent=self)
            return

        name = prof.get("full_name") or prof.get("username", "")
        role = prof.get("role", "")
        if not messagebox.askyesno(
                "Delete User",
                f"Permanently delete this account?\n\n"
                f"  Name:  {name}\n"
                f"  Role:  {role}\n"
                f"  Email: {prof.get('email', '')}\n\n"
                "Their orders will be kept but unlinked.\n"
                "This cannot be undone.",
                parent=self):
            return

        self._status.set("Deleting user…")
        self.update()
        q = queue.Queue()

        def _work():
            try:
                self._db.delete_user_account(prof["id"])
                q.put(("ok", None))
            except Exception as exc:
                q.put(("error", str(exc)))

        def _poll():
            try:
                while True:
                    kind, data = q.get_nowait()
                    if kind == "ok":
                        self._status.set(f"User '{name}' deleted.")
                        self._load()
                        return
                    elif kind == "error":
                        messagebox.showerror("Delete Failed", data, parent=self)
                        self._status.set("Delete failed.")
                        return
            except queue.Empty:
                pass
            self.after(50, _poll)

        threading.Thread(target=_work, daemon=True).start()
        self.after(50, _poll)

    def _create_user(self):
        caller_level = self._db.role_level()
        if caller_level < 3:
            messagebox.showwarning("No Permission",
                                   "You do not have permission to create users.",
                                   parent=self)
            return
        CreateUserDialog(self, self._db, on_done=self._load)

    def _change_role(self):
        prof = self._get_selected_profile()
        if not prof:
            messagebox.showinfo("Change Role", "Select a user first.", parent=self)
            return
        caller_role  = self._db.current_role()
        caller_level = self._db.role_level(caller_role)

        # Determine which roles this caller can assign
        if caller_level >= 4:          # Director / Admin
            assignable = ALL_ROLES
        elif caller_level >= 3:        # Manager
            assignable = ["Employee"]
        else:
            messagebox.showwarning("No Permission",
                                   "You do not have permission to change roles.",
                                   parent=self)
            return

        RolePickerDialog(self, prof, assignable, self._db, on_done=self._load)


class RolePickerDialog(tk.Toplevel):
    def __init__(self, master, profile: dict, assignable: list, db, on_done=None):
        super().__init__(master)
        self.title("Change Role")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.configure(bg=CBG)
        self._db      = db
        self._profile = profile
        self._on_done = on_done

        hdr = tk.Frame(self, bg=CA, padx=16, pady=10)
        hdr.pack(fill="x")
        name = profile.get("full_name") or profile.get("username", "")
        tk.Label(hdr, text=f"Change role — {name}",
                 bg=CA, fg="white", font=F_BOLD).pack(anchor="w")
        tk.Label(hdr, text=f"Current role: {profile.get('role', 'Employee')}",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        body = tk.Frame(self, bg=CBG, padx=20, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="New role:", bg=CBG, fg=CTX,
                 font=F_BOLD).pack(anchor="w", pady=(0, 6))

        self._role_var = tk.StringVar(value=profile.get("role", "Employee"))
        for role in assignable:
            colour = ROLE_COLOURS.get(role, CNE)
            rb = tk.Radiobutton(body, text=f"  {role}",
                                variable=self._role_var, value=role,
                                bg=CBG, fg=colour, font=F_BOLD,
                                activebackground=CBG, selectcolor=CCA,
                                cursor="hand2")
            rb.pack(anchor="w", pady=2)

        self._status = tk.StringVar()
        tk.Label(body, textvariable=self._status, bg=CBG, fg=CRD,
                 font=F_SM).pack(anchor="w", pady=(10, 0))

        foot = tk.Frame(self, bg=CBG, padx=20, pady=14)
        foot.pack(fill="x")
        _flat_btn(foot, "Cancel", self.destroy,
                  bg=CNE, pady=11, padx=28, font=F_BOLD).pack(side="right", padx=(10, 0))
        self._save_btn = _flat_btn(foot, "Save Role", self._save,
                                    bg=CGR, pady=11, padx=28, font=F_BOLD)
        self._save_btn.pack(side="right")

        self.update_idletasks()
        W, H = 380, 340
        px = master.winfo_rootx() + master.winfo_width()  // 2 - W // 2
        py = master.winfo_rooty() + master.winfo_height() // 2 - H // 2
        self.geometry(f"{W}x{H}+{px}+{py}")

    def _save(self):
        new_role = self._role_var.get()
        self._save_btn.config(state="disabled", text="Saving…")
        self._status.set("")
        self.update()

        q = queue.Queue()

        def _work():
            try:
                self._db.update_user_role(self._profile["id"], new_role)
                q.put(("ok", None))
            except Exception as exc:
                q.put(("error", str(exc)))

        def _poll():
            try:
                while True:
                    kind, data = q.get_nowait()
                    if kind == "ok":
                        self._done()
                        return
                    elif kind == "error":
                        self._status.set(f"Error: {data}")
                        self._save_btn.config(state="normal", text="Save Role")
                        return
            except queue.Empty:
                pass
            self.after(50, _poll)

        threading.Thread(target=_work, daemon=True).start()
        self.after(50, _poll)

    def _done(self):
        self.destroy()
        if self._on_done:
            self._on_done()


# ── Create User Dialog ────────────────────────────────────────────────────────

class CreateUserDialog(tk.Toplevel):
    """
    Lets Directors, Admins and Managers create a new user account.
    Managers can only create Employee accounts.
    """

    def __init__(self, master, db, on_done=None):
        super().__init__(master)
        self.title("Create User")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.configure(bg=CBG)
        self._db      = db
        self._on_done = on_done

        caller_level = db.role_level()

        # Which roles can be assigned by this caller
        if caller_level >= 4:
            self._assignable_roles = ALL_ROLES
        else:
            self._assignable_roles = ["Employee"]

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=CA, padx=16, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Create New User",
                 bg=CA, fg="white", font=F_SEC).pack(anchor="w")
        tk.Label(hdr, text="An account will be created and a confirmation email sent.",
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        # ── Body ──────────────────────────────────────────────────────────────
        body = tk.Frame(self, bg=CBG, padx=20, pady=16)
        body.pack(fill="both", expand=True)

        def _field(label):
            tk.Label(body, text=label, bg=CBG, fg=CTX, font=F_BOLD,
                     anchor="w").pack(fill="x")
            e = tk.Entry(body, relief="solid", bd=1, font=F_BODY,
                         bg="#FFFFFF", fg=CTX, insertbackground=CTX)
            e.pack(fill="x", pady=(2, 10))
            return e

        self._name  = _field("Full Name")
        self._email = _field("Email Address")

        tk.Label(body, text="Password  (leave blank to auto-generate a temporary one)",
                 bg=CBG, fg=CTX, font=F_BOLD, anchor="w").pack(fill="x")
        self._pw = tk.Entry(body, show="•", relief="solid", bd=1, font=F_BODY,
                            bg="#FFFFFF", fg=CTX, insertbackground=CTX)
        self._pw.pack(fill="x", pady=(2, 4))
        tk.Label(body,
                 text="If blank, a secure temp password is generated and shown to you after creation.",
                 bg=CBG, fg=CMU, font=F_SM).pack(anchor="w", pady=(0, 8))

        # Role selector
        tk.Label(body, text="Role", bg=CBG, fg=CTX, font=F_BOLD,
                 anchor="w").pack(fill="x")
        self._role_var = tk.StringVar(value=self._assignable_roles[0])
        role_row = tk.Frame(body, bg=CBG)
        role_row.pack(fill="x", pady=(2, 10))
        for role in self._assignable_roles:
            colour = ROLE_COLOURS.get(role, CNE)
            tk.Radiobutton(role_row, text=f"  {role}",
                           variable=self._role_var, value=role,
                           bg=CBG, fg=colour, font=F_BOLD,
                           activebackground=CBG, selectcolor="#FFFFFF",
                           cursor="hand2").pack(side="left", padx=(0, 16))

        self._status = tk.StringVar()
        self._status_lbl = tk.Label(body, textvariable=self._status,
                                     bg=CBG, fg=CRD, font=F_SM,
                                     wraplength=360, justify="left")
        self._status_lbl.pack(fill="x")

        # ── Footer ────────────────────────────────────────────────────────────
        foot = tk.Frame(self, bg=CBG, padx=20, pady=14)
        foot.pack(fill="x")
        _flat_btn(foot, "Cancel", self.destroy,
                  bg=CNE, pady=11, padx=28, font=F_BOLD).pack(side="right", padx=(10, 0))
        self._create_btn = _flat_btn(foot, "Create User", self._create,
                                      bg=CGR, pady=11, padx=28, font=F_BOLD)
        self._create_btn.pack(side="right")

        self.update_idletasks()
        W, H = 420, 480
        px = master.winfo_rootx() + master.winfo_width()  // 2 - W // 2
        py = master.winfo_rooty() + master.winfo_height() // 2 - H // 2
        self.geometry(f"{W}x{H}+{px}+{py}")
        self._name.focus_set()

    def _create(self):
        name  = self._name.get().strip()
        email = self._email.get().strip()
        pw    = self._pw.get()
        role  = self._role_var.get()

        if not name:
            self._status.set("Please enter a full name.")
            return
        if not email:
            self._status.set("Please enter an email address.")
            return
        # If password left blank, generate a secure temp password
        self._temp_pw = None
        if not pw:
            import secrets, string
            alphabet = string.ascii_letters + string.digits + "!@#$%"
            pw = "".join(secrets.choice(alphabet) for _ in range(14))
            self._temp_pw = pw
        elif len(pw) < 6:
            self._status.set("Password must be at least 6 characters.")
            return

        self._create_btn.config(state="disabled", text="Creating…")
        self._status_lbl.config(fg=CMU)
        self._status.set("Creating account…")
        self.update()

        q = queue.Queue()

        def _work():
            try:
                result = self._db.create_user_account(email, pw, name, role)
                q.put(("ok", result))
            except Exception as exc:
                msg = str(exc)
                if "already registered" in msg.lower() or "already exists" in msg.lower():
                    msg = "An account with that email already exists."
                q.put(("error", msg))

        def _poll():
            try:
                while True:
                    kind, data = q.get_nowait()
                    if kind == "ok":
                        uname = data.get("username", "")
                        self._status_lbl.config(fg="#1E8449")
                        msg = (f"User created: {uname} ({data.get('role', role)})\n"
                               f"Email: {data.get('email', email)}")
                        if getattr(self, "_temp_pw", None):
                            msg += f"\n\nTemp password (share with user):\n{self._temp_pw}"
                            # Also show in a popup so it can be copied
                            messagebox.showinfo(
                                "User Created — Temp Password",
                                f"Account created for {data.get('email', email)}\n\n"
                                f"Temporary password:\n\n  {self._temp_pw}\n\n"
                                "Share this with the user so they can sign in.\n"
                                "They should change it in Settings → Change Password.",
                                parent=self)
                        self._status.set(msg)
                        self._create_btn.config(state="disabled", text="Created")
                        if self._on_done:
                            self.after(1200, self._on_done)
                        self.after(1500, self.destroy)
                        return
                    elif kind == "error":
                        self._status.set(data)
                        self._status_lbl.config(fg=CRD)
                        self._create_btn.config(state="normal", text="Create User")
                        return
            except queue.Empty:
                pass
            self.after(50, _poll)

        threading.Thread(target=_work, daemon=True).start()
        self.after(50, _poll)  # end CreateUserDialog


# ── Edit Profile Dialog ───────────────────────────────────────────────────────

class EditProfileDialog(tk.Toplevel):
    """Directors and Admins can edit any user's full name and username."""

    def __init__(self, master, profile: dict, db, on_done=None):
        super().__init__(master)
        self.title("Edit Profile")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.configure(bg=CBG)
        self._db      = db
        self._profile = profile
        self._on_done = on_done

        name = profile.get("full_name") or profile.get("username", "")

        hdr = tk.Frame(self, bg=CA, padx=16, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"Edit Profile — {name}",
                 bg=CA, fg="white", font=F_SEC).pack(anchor="w")
        tk.Label(hdr, text=profile.get("email", ""),
                 bg=CA, fg="#A9CCE3", font=F_SM).pack(anchor="w")

        body = tk.Frame(self, bg=CBG, padx=20, pady=16)
        body.pack(fill="both", expand=True)

        def _field(label, initial):
            tk.Label(body, text=label, bg=CBG, fg=CTX,
                     font=F_BOLD, anchor="w").pack(fill="x")
            e = tk.Entry(body, relief="solid", bd=1, font=F_BODY,
                         bg="#FFFFFF", fg=CTX, insertbackground=CTX)
            e.insert(0, initial)
            e.pack(fill="x", pady=(2, 12))
            return e

        self._name_entry     = _field("Full Name", profile.get("full_name", ""))
        self._username_entry = _field("Username",  profile.get("username", ""))

        tk.Label(body, text="Username must be unique across all users.",
                 bg=CBG, fg=CMU, font=F_SM).pack(anchor="w", pady=(0, 10))

        self._status = tk.StringVar()
        self._status_lbl = tk.Label(body, textvariable=self._status,
                                     bg=CBG, fg=CRD, font=F_SM, wraplength=340)
        self._status_lbl.pack(fill="x")

        foot = tk.Frame(self, bg=CBG, padx=20, pady=14)
        foot.pack(fill="x")
        _flat_btn(foot, "Cancel", self.destroy,
                  bg=CNE, pady=11, padx=28, font=F_BOLD).pack(side="right", padx=(10, 0))
        self._save_btn = _flat_btn(foot, "Save Changes", self._save,
                                    bg=CGR, pady=11, padx=28, font=F_BOLD)
        self._save_btn.pack(side="right")

        self.update_idletasks()
        W, H = 400, 360
        px = master.winfo_rootx() + master.winfo_width()  // 2 - W // 2
        py = master.winfo_rooty() + master.winfo_height() // 2 - H // 2
        self.geometry(f"{W}x{H}+{px}+{py}")
        self._name_entry.focus_set()
        self._name_entry.bind("<Return>", lambda e: self._username_entry.focus_set())
        self._username_entry.bind("<Return>", lambda e: self._save())

    def _save(self):
        full_name = self._name_entry.get().strip()
        username  = self._username_entry.get().strip()

        if not full_name:
            self._status.set("Full name cannot be empty.")
            return
        if not username:
            self._status.set("Username cannot be empty.")
            return

        self._save_btn.config(state="disabled", text="Saving…")
        self._status.set("")
        self.update()

        q = queue.Queue()

        def _work():
            try:
                self._db.update_user_profile(self._profile["id"], full_name, username)
                q.put(("ok", None))
            except Exception as exc:
                q.put(("error", str(exc)))

        def _poll():
            try:
                while True:
                    kind, data = q.get_nowait()
                    if kind == "ok":
                        self._status_lbl.config(fg="#1E8449")
                        self._status.set("Saved successfully.")
                        self._save_btn.config(state="disabled", text="Saved")
                        if self._on_done:
                            self.after(800, self._on_done)
                        self.after(1000, self.destroy)
                        return
                    elif kind == "error":
                        self._status.set(data)
                        self._status_lbl.config(fg=CRD)
                        self._save_btn.config(state="normal", text="Save Changes")
                        return
            except queue.Empty:
                pass
            self.after(50, _poll)

        threading.Thread(target=_work, daemon=True).start()
        self.after(50, _poll)
