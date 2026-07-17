"""One-shot: upload dist/TAFOrderEntry.exe and set version 1.0.1"""
import json, os, sys, datetime, getpass

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# Load settings
with open(os.path.join(ROOT, "settings.json"), encoding="utf-8") as f:
    settings = json.load(f)
anon_key = settings["supabase_anon_key"].strip()

SUPABASE_URL = "https://djexdkwohkylunnwbxpf.supabase.co"
VERSION      = "1.0.1"
NOTES        = "Search/filter on orders list + bag PDF fix"
EXE          = os.path.join(ROOT, "dist", "TAFOrderEntry.exe")

from supabase import create_client

client = create_client(SUPABASE_URL, anon_key)

email    = input("Director email: ").strip()
password = getpass.getpass("Password: ")
client.auth.sign_in_with_password({"email": email, "password": password})
print("Signed in.")

print(f"Uploading {os.path.getsize(EXE)/1_048_576:.1f} MB ...")
with open(EXE, "rb") as f:
    data = f.read()

try:
    client.storage.from_("releases").remove(["TAFOrderEntry.exe"])
except Exception:
    pass

client.storage.from_("releases").upload(
    "TAFOrderEntry.exe", data,
    file_options={"content-type": "application/octet-stream", "upsert": "true"},
)

url = f"{SUPABASE_URL}/storage/v1/object/public/releases/TAFOrderEntry.exe"

client.table("app_versions").upsert({
    "id": 1,
    "version": VERSION,
    "download_url": url,
    "release_notes": NOTES,
    "updated_at": datetime.datetime.utcnow().isoformat(),
}).execute()

print(f"\nDone! Version {VERSION} is now live.")
print(f"URL: {url}")
input("\nPress Enter to close...")
