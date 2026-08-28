from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

datas = collect_data_files('streamlit')
datas += copy_metadata('streamlit', recursive=True)
datas += copy_metadata('pywebview', recursive=True)
datas += [('app.py', '.'), ('mtg_downloader/assets', 'mtg_downloader/assets')]
hiddenimports = collect_submodules('streamlit')
hiddenimports += collect_submodules('mtg_downloader', filter=lambda name: name != 'mtg_downloader.app')
hiddenimports += ['webview.platforms.edgechromium', 'webview.platforms.winforms', 'pandas', 'pypdf', 'reportlab', 'httpx']

a = Analysis(['desktop.py'], pathex=[], binaries=[], datas=datas,
             hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
             excludes=['pytest', 'tkinter', 'matplotlib', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ProxyMaker',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ProxyMaker')
