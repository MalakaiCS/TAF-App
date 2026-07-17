"""
Developer tool: release a new app version via GitHub.

What it does:
  1. Sets APP_VERSION (taf_order_app/updater.py) and AppVersion (installer.iss)
     to the new version.
  2. Commits the bump.
  3. Creates and pushes tag  v<version>  (and pushes main).

Pushing the tag triggers the "Build Windows EXE" GitHub Actions workflow,
which builds the installer and publishes a GitHub Release. Every installed
client then sees the update on next launch (see taf_order_app/updater.py).

Usage:
    python push_update.py 2.0.1 "Fixed the thing, added the other thing"
    python push_update.py            # prompts for version + notes
"""
import os, re, sys, subprocess

ROOT      = os.path.dirname(os.path.abspath(__file__))
UPDATER   = os.path.join(ROOT, "taf_order_app", "updater.py")
INSTALLER = os.path.join(ROOT, "installer.iss")


def _run(*args):
    print("  $", " ".join(args))
    subprocess.run(args, cwd=ROOT, check=True)


def _replace(path, pattern, replacement, label):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    new, n = re.subn(pattern, replacement, text, count=1)
    if n != 1:
        raise SystemExit(f"ERROR: could not update {label} in {os.path.basename(path)}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)


def main():
    args = sys.argv[1:]
    version = args[0].strip().lstrip("vV") if args else input("New version (e.g. 2.0.1): ").strip().lstrip("vV")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit("ERROR: version must look like 2.0.1")
    notes = " ".join(args[1:]).strip() if len(args) > 1 else input("Release notes (optional): ").strip()

    print(f"\nReleasing v{version} …")
    _replace(UPDATER,   r'APP_VERSION\s*=\s*"[^"]+"', f'APP_VERSION = "{version}"', "APP_VERSION")
    _replace(INSTALLER, r'AppVersion=[^\r\n]+',       f'AppVersion={version}',      "AppVersion")

    _run("git", "add", "taf_order_app/updater.py", "installer.iss")
    _run("git", "commit", "-m", f"Release v{version}" + (f"\n\n{notes}" if notes else ""))
    _run("git", "tag", "-a", f"v{version}", "-m", (notes or f"v{version}"))
    _run("git", "push", "origin", "main")
    _run("git", "push", "origin", f"v{version}")

    print(f"\nDone. Tag v{version} pushed.")
    print("GitHub Actions is now building the installer and publishing the release:")
    print("  https://github.com/MalakaiCS/TAF-App/actions")
    print("Once the release is live, installed clients will auto-update.")


if __name__ == "__main__":
    main()
