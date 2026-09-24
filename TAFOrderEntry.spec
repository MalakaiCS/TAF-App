# -*- mode: python ; coding: utf-8 -*-
#
# ONE-DIRECTORY build (not one-file).
# Reason: one-file mode extracts to a temp _MEI folder and locks python3xx.dll
# there, causing a "Failed to remove temporary directory" warning on every exit.
# In one-dir mode all files live permanently next to the exe — no temp folder,
# no cleanup, no warning.
#
import os
import sys
from PyInstaller.utils.hooks import collect_data_files

WINDOWS = sys.platform == 'win32'
MACOS   = sys.platform == 'darwin'

# Collect all babel locale data files properly (1000+ .dat files + global.dat)
babel_datas = collect_data_files('babel', include_py_files=False)

# SumatraPDF.exe lets us print PDFs without a PDF viewer. CI fetches it (from
# the pinned pdf-to-printer npm package) before the build; if it's absent
# (e.g. a local source build) we simply don't bundle it and the app falls back
# to the Windows shell 'print' verb. It is a Windows program: on a Mac the
# printing path is lpr, which is already there, so there is nothing to bundle.
pdf_helper_datas = ([('SumatraPDF.exe', '.')]
                    if WINDOWS and os.path.exists('SumatraPDF.exe') else [])

# pywin32 is not installed off Windows and never will be. Listing it as a
# hidden import there is not a warning, it is a build that stops.
windows_imports = ['win32com', 'win32com.client', 'win32print', 'win32api',
                   'pywintypes'] if WINDOWS else []

# The icon: Windows wants .ico, macOS wants .icns, and PyInstaller refuses a
# format the platform does not take. CI makes the .icns from the same PNG the
# rest of the app uses, so it is one logo rather than two that can drift.
if WINDOWS:
    app_icon = ['TAF_logo.ico']
elif MACOS and os.path.exists('TAF_logo.icns'):
    app_icon = ['TAF_logo.icns']
else:
    app_icon = None

a = Analysis(
    ['modern_order_gui.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('TAF_logo.ico',            '.'),
        ('TAF_logo.png',            '.'),
        ('TAF_logo_horizontal.png', '.'),
        ('TAF_logo_circular.png',   '.'),
        ('Templates.xlsx',          '.'),
        ('settings.json',           '.'),
        ('fonts',                   'fonts'),   # bundled Public Sans .ttf files
        ('THIRD_PARTY_NOTICES.txt', '.'),       # SumatraPDF GPLv3 notice
    ] + babel_datas + pdf_helper_datas,
    hiddenimports=[
        # supabase + deps
        'supabase',
        'supabase._sync',
        'supabase._async',
        'supabase_auth',
        'postgrest',
        'postgrest._sync',
        'postgrest._async',
        'storage3',
        'realtime',
        'gotrue',
        'httpx',
        'httpcore',
        'anyio',
        'anyio._backends._asyncio',
        'anyio._backends._trio',
        'h2',
        'hpack',
        'hyperframe',
        'certifi',
        'charset_normalizer',
        'websockets',
        # taf_order_app internals
        'taf_order_app',
        'taf_order_app.db',
        'taf_order_app.login_window',
        'taf_order_app.user_management',
        'taf_order_app.order_service',
        'taf_order_app.models',
        'taf_order_app.validation',
        'taf_order_app.bag_filler',
        'taf_order_app.po_import',
        'taf_order_app.phone_page',
        # Phone-pairing QR code
        'qrcode',
        'qrcode.image.pil',
        # Calendar picker
        'tkcalendar',
        'babel',
        'babel.numbers',
        'babel.dates',
        'babel.core',
        'babel.localedata',
        # PDF generation
        'reportlab',
        'reportlab.platypus',
        'reportlab.lib',
        'reportlab.lib.pagesizes',
        'reportlab.lib.units',
        'reportlab.lib.colors',
        'reportlab.lib.styles',
        'reportlab.lib.enums',
        'reportlab.pdfgen',
        'pdf_generator',
        # Pillow (type-badge rendering + logos)
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        'PIL.ImageTk',
        # office / PDF
        'openpyxl',
        'openpyxl.styles',
        'openpyxl.utils',
        'pypdf',
        'docx',
        'docx.oxml',
        # stdlib extras sometimes missed
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'tkinter.filedialog',
        'queue',
        'threading',
        'calendar',
    ] + windows_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # binaries go into COLLECT, not into the exe
    name='TAFOrderEntry',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX is a Windows habit here and it is actively harmful on a Mac: it
    # rewrites the binaries, which breaks the ad-hoc signature every
    # arm64 executable must carry, and the app is then killed on launch.
    upx=WINDOWS,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=app_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=WINDOWS,
    upx_exclude=[],
    name='TAFOrderEntry',   # output folder: dist/TAFOrderEntry/
)

# A folder full of files is how Windows ships. A Mac ships one thing you drag
# to Applications, and a plain executable there has no Dock icon, no name in
# the menu bar, and no way to be the default for anything. BUNDLE wraps the
# same COLLECT output in TAF Order Entry.app, which is that one thing.
if MACOS:
    app = BUNDLE(
        coll,
        name='TAF Order Entry.app',
        icon='TAF_logo.icns' if os.path.exists('TAF_logo.icns') else None,
        bundle_identifier='au.com.totalairfiltration.orderentry',
        info_plist={
            'CFBundleName':             'TAF Order Entry',
            'CFBundleDisplayName':      'TAF Order Entry',
            'CFBundleShortVersionString': os.environ.get('TAF_VERSION', '0.0.0'),
            'CFBundleVersion':            os.environ.get('TAF_VERSION', '0.0.0'),
            # Retina. Without it the whole window is drawn at half resolution
            # and then scaled up, which looks like a screenshot of itself.
            'NSHighResolutionCapable':  True,
            'NSRequiresAquaSystemAppearance': False,
            'LSMinimumSystemVersion':   '11.0',
        },
    )
