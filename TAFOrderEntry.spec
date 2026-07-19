# -*- mode: python ; coding: utf-8 -*-
#
# ONE-DIRECTORY build (not one-file).
# Reason: one-file mode extracts to a temp _MEI folder and locks python3xx.dll
# there, causing a "Failed to remove temporary directory" warning on every exit.
# In one-dir mode all files live permanently next to the exe — no temp folder,
# no cleanup, no warning.
#
import os
from PyInstaller.utils.hooks import collect_data_files

# Collect all babel locale data files properly (1000+ .dat files + global.dat)
babel_datas = collect_data_files('babel', include_py_files=False)

# PDFtoPrinter.exe lets us print PDFs without a PDF viewer. CI downloads it
# before the build; if it's absent (e.g. a local source build) we simply don't
# bundle it and the app falls back to the Windows shell 'print' verb.
pdf_helper_datas = [('PDFtoPrinter.exe', '.')] if os.path.exists('PDFtoPrinter.exe') else []

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
        'win32com',
        'win32com.client',
        'win32print',   # get/set default printer for the Print feature
        'win32api',
        'pywintypes',
        # stdlib extras sometimes missed
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'tkinter.filedialog',
        'queue',
        'threading',
        'calendar',
    ],
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
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['TAF_logo.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TAFOrderEntry',   # output folder: dist/TAFOrderEntry/
)
