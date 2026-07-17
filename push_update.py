"""
Developer tool: build, upload and push a new app version.

Usage:
    python push_update.py

Steps:
  1. Asks for the new version number (e.g. 1.1.0)
  2. Asks for release notes
  3. Builds the EXE with PyInstaller
  4. Uploads dist/TAFOrderEntry.exe to Supabase Storage (bucket: releases)
  5. Updates the app_versions table so all clients see the new version

Prerequisites:
  - You must have Director or Admin role
  - The 'releases' storage bucket must exist and be PUBLIC in Supabase
    (Dashboard → Storage → New bucket → name: releases → Public: ON)
  - Run migrate_updater.sql first if you haven't already
"""
import json, os, sys, subprocess, importlib.util, getpass, traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# Load db directly to avoid openpyxl dependency
_spec = importlib.util.spec_from_file_location(
    "taf_order_app.db", os.path.join(ROOT, "taf_order_app", "db.py")
)
db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(db)

# Load updater directly
_spec2 = importlib.util.spec_from_file_location(
    "taf_order_app.updater", os.path.join(ROOT, "taf_order_app", "updater.py")
)
updater = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(updater)


def main():
    print("=" * 55)
    print("  TAF Order App — Push Update Tool")
    print("=" * 55)

    # Load API key
    settings_path = os.path.join(ROOT, "settings.json")
    with open(settings_path, encoding="utf-8") as f:
        settings = json.load(f)
    anon_key = settings.get("supabase_anon_key", "").strip()
    if not anon_key:
        print("ERROR: No supabase_anon_key in settings.json")
        return

    db.init(anon_key)
    print("Connected to Supabase.")

    # Sign in
    email    = input("\nDirector/Admin email: ").strip()
    password = getpass.getpass("Password: ")
    db.sign_in(email, password)
    role = db.current_role()
    print(f"Signed in as: {db.current_username()} ({role})")
    if role not in ("Director", "Admin"):
        print("ERROR: Only Directors and Admins can push updates.")
        return

    # Current version
    current = updater.get_current_remote_version()
    print(f"\nCurrent live version: {current}")

    # New version
    new_version = input("New version number (e.g. 1.1.0): ").strip()
    if not new_version:
        print("Cancelled.")
        return

    release_notes = input("Release notes (optional): ").strip()

    # Build EXE
    build = input("\nBuild EXE now? (Y/n): ").strip().lower()
    if build != "n":
        print("\nBuilding EXE...")
        result = subprocess.run(
            [sys.executable, "-m", "PyInstaller", "TAFOrderEntry.spec", "--noconfirm"],
            cwd=ROOT
        )
        if result.returncode != 0:
            print("ERROR: PyInstaller build failed.")
            return
        print("Build complete.")

    exe_path = os.path.join(ROOT, "dist", "TAFOrderEntry.exe")
    if not os.path.exists(exe_path):
        print(f"ERROR: EXE not found at {exe_path}")
        return

    size_mb = os.path.getsize(exe_path) / 1_048_576
    print(f"\nEXE size: {size_mb:.1f} MB")
    confirm = input(f"Upload version {new_version} and make it live? (Y/n): ").strip().lower()
    if confirm == "n":
        print("Cancelled.")
        return

    print("\nUploading to Supabase Storage...")
    print("(This may take a minute depending on file size)")

    url = updater.upload_and_push(exe_path, new_version, release_notes, anon_key)

    print(f"\nDone!")
    print(f"  Version:  {new_version}")
    print(f"  URL:      {url}")
    print(f"  Notes:    {release_notes or '(none)'}")
    print("\nAll clients will see the update prompt on next launch.")


try:
    main()
except Exception:
    print("\n--- Error ---")
    traceback.print_exc()

print()
input("Press Enter to close...")
