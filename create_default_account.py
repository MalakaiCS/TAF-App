"""
One-time script: creates the default Director account for Kai Brown.
Double-click this file, OR run:  python create_default_account.py
"""
import json, sys, os, importlib.util, traceback

def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    # Load db module directly (avoids needing openpyxl etc.)
    _spec = importlib.util.spec_from_file_location(
        "taf_order_app.db",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "taf_order_app", "db.py"),
    )
    db = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(db)

    # Load API key from settings.json
    settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
    if not os.path.exists(settings_path):
        print("ERROR: settings.json not found.")
        return

    with open(settings_path, encoding="utf-8") as f:
        settings = json.load(f)

    anon_key = settings.get("supabase_anon_key", "").strip()
    if not anon_key:
        print("ERROR: No supabase_anon_key in settings.json.")
        return

    print("Connecting to Supabase...")
    db.init(anon_key)
    print("Connected.")

    # Check tables
    print("Checking database tables...")
    profiles_ok, orders_ok = db.tables_exist()
    if not profiles_ok:
        print()
        print("ERROR: 'profiles' table does not exist yet.")
        print()
        print("Run setup_database.sql in Supabase SQL Editor first:")
        print("  https://supabase.com/dashboard/project/djexdkwohkylunnwbxpf/sql/new")
        print()
        print("Paste the contents of setup_database.sql and click Run,")
        print("then run this script again.")
        return

    print("Tables OK.")

    import os, getpass
    EMAIL     = os.environ.get("TAF_ADMIN_EMAIL")    or input("Admin email: ").strip()
    PASSWORD  = os.environ.get("TAF_ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    FULL_NAME = os.environ.get("TAF_ADMIN_NAME")     or input("Full name: ").strip()
    ROLE      = os.environ.get("TAF_ADMIN_ROLE", "Director")

    print(f"\nSetting up account: {EMAIL}")

    def make_profile(user_id, user_email):
        username = db.generate_username(FULL_NAME)
        db.create_profile(user_id, user_email, FULL_NAME, username, ROLE)
        return username

    def ensure_correct_profile(user_id, username):
        """Make sure the profile has the right name, username and role."""
        db.get_client().table("profiles").update(
            {"role": ROLE, "full_name": FULL_NAME, "username": username}
        ).eq("id", user_id).execute()

    # ── Step 1: Sign up (creates auth user) ───────────────────────────────────
    signed_in = False
    user_id   = None

    try:
        user = db.sign_up(EMAIL, PASSWORD)
        if user and user.id:
            user_id = str(user.id)
            print("  Auth account created.")

            # sign_up sets the session if email confirmation is disabled
            if db.current_user():
                print("  Session active (email confirmation disabled).")
                signed_in = True
            else:
                # Email confirmation required — try sign_in anyway
                print("  Trying to sign in...")
                try:
                    db.sign_in(EMAIL, PASSWORD)
                    signed_in = True
                    user_id = str(db.current_user().id)
                    print("  Signed in successfully.")
                except Exception as si_err:
                    if "Email not confirmed" in str(si_err):
                        print()
                        print("  Email confirmation is required by your Supabase project.")
                        print(f"  A confirmation email was sent to {EMAIL}.")
                        print()
                        print("  To skip email confirmation (recommended for internal apps):")
                        print("  1. Go to: https://supabase.com/dashboard/project/djexdkwohkylunnwbxpf/auth/providers")
                        print("  2. Under Email provider, turn OFF 'Confirm email'")
                        print("  3. Run this script again.")
                        print()
                        print("  OR: Confirm the email, then run this script again.")
                        return
                    else:
                        raise

    except Exception as exc:
        msg = str(exc)
        if "already registered" in msg.lower() or "User already registered" in msg:
            print("  Account already exists. Signing in...")
            try:
                db.sign_in(EMAIL, PASSWORD)
                signed_in = True
                user_id = str(db.current_user().id)
                print("  Signed in.")
            except Exception as e2:
                print(f"  ERROR signing in: {e2}")
                return
        else:
            print(f"  ERROR during sign-up: {exc}")
            traceback.print_exc()
            return

    if not signed_in or not user_id:
        print("Could not establish a session. Cannot create profile.")
        return

    # ── Step 2: Create / update profile ──────────────────────────────────────
    # Determine the correct username (KBrown for Kai Brown)
    target_username = "KBrown"

    prof = db.current_profile()
    if prof:
        current_ok = (
            prof.get("role") == ROLE
            and prof.get("full_name") == FULL_NAME
            and prof.get("username") == target_username
        )
        if not current_ok:
            ensure_correct_profile(user_id, target_username)
            db.reload_profile()
            prof = db.current_profile()
            print(f"  Profile updated: {prof.get('username')} ({ROLE})")
        else:
            print(f"  Profile already correct: {target_username} ({ROLE})")
        username = target_username
    else:
        db.get_client().table("profiles").upsert({
            "id": user_id, "email": EMAIL,
            "full_name": FULL_NAME, "username": target_username, "role": ROLE,
        }).execute()
        username = target_username
        print(f"  Profile created: {username} ({ROLE})")

    # ── Done ──────────────────────────────────────────────────────────────────
    print()
    print("SUCCESS! Account is fully set up.")
    print(f"  Email:    {EMAIL}")
    print(f"  Password: {PASSWORD}")
    print(f"  Username: {username}  |  Role: {ROLE}")
    print()
    print("You can now launch the app:  python modern_order_gui.py")


try:
    main()
except Exception:
    print("\n--- Unexpected error ---")
    traceback.print_exc()

print()
input("Press Enter to close...")
