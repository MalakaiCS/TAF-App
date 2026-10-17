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

WINDOWS = sys.platform == 'win32'
MACOS   = sys.platform == 'darwin'

# No Babel: its 1000+ locale files came in for tkcalendar's date picker,
# which the app no longer uses (its own picker starts instantly). Fewer files
# to install, and fewer for antivirus to look through on every launch.

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
        ('TAF_logo_header.png',     '.'),       # the logos at screen size
        ('TAF_logo_login.png',      '.'),
        ('TAF_logo_circular.png',   '.'),
        ('TAF_logo_badge.png',      '.'),       # the round badge that turns
        ('Templates.xlsx',          '.'),
        ('settings.json',           '.'),
        ('fonts',                   'fonts'),   # bundled Public Sans .ttf files
        ('THIRD_PARTY_NOTICES.txt', '.'),       # SumatraPDF GPLv3 notice
    ] + pdf_helper_datas,
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
        'taf_order_app.quiet',
        'taf_order_app.tls',
        'taf_order_app.db_session',
        'taf_order_app.bag_filler',
        'taf_order_app.po_import',
        'taf_order_app.phone_page',
        # Reached only from inside functions (the worksheet's blocks under
        # Notes, the labels), so named here rather than left to discovery.
        'taf_order_app.worksheet_blocks',
        'taf_order_app.cchannel',
        'taf_order_app.pallet_labels',
        'taf_order_app.order_packing',
        'taf_order_app.delivery_labels',
        'taf_order_app.filter_calc',
        'taf_order_app.calc_settings',
        'reportlab.lib.utils',
        # Phone-pairing QR code
        'qrcode',
        'qrcode.image.pil',
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
    # Never used by the app; left out so the bundle is smaller and starts
    # faster.
    excludes=['tkcalendar', 'babel', 'matplotlib', 'pandas', 'IPython',
              'pytest'],
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
    # No UPX anywhere. On a Mac it breaks the signature every arm64 program
    # must carry; on Windows every compressed DLL is unpacked again at every
    # launch, and antivirus looks harder at packed files - both slow start-up
    # for a smaller download nobody needed.
    upx=False,
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
    upx=False,
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
