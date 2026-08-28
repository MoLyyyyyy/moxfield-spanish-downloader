"""Build on Windows with: python -m pip install -r requirements-desktop.txt."""
import os
import shutil
import subprocess
import struct
import sys
from pathlib import Path


def main():
    if sys.platform != 'win32':
        raise SystemExit('El ejecutable de Windows debe compilarse en Windows.')
    if struct.calcsize('P') != 8:
        raise SystemExit('Usa Python de 64 bits para compilar la versión Windows x64.')
    root = Path(__file__).resolve().parent
    os.chdir(root)
    os.environ['PYINSTALLER_CONFIG_DIR'] = str(root / 'build' / 'pyinstaller-cache')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', 'ProxyMaker.spec'], check=True)
    distribution = root / 'dist' / 'ProxyMaker'
    for name in ('PORTABLE.txt', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(root / name, distribution / name)
    archive = shutil.make_archive(str(root / 'dist' / 'ProxyMaker-Windows-portable'), 'zip', root / 'dist', 'ProxyMaker')
    print(archive)


if __name__ == '__main__':
    main()
