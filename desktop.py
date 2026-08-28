"""Portable Windows host. The server is a child process, never a public service."""
from __future__ import annotations

import argparse
import contextlib
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path


def server_options(port: int) -> dict:
    from mtg_downloader.studio_ui import theme_options
    return {
        **theme_options(),
        'server.address': '127.0.0.1',
        'server.port': port,
        'server.headless': True,
        'server.fileWatcherType': 'none',
        'server.runOnSave': False,
        'server.enableXsrfProtection': True,
        'server.enableCORS': True,
        'server.maxMessageSize': 500,
        'browser.gatherUsageStats': False,
        'global.developmentMode': False,
        'client.toolbarMode': 'minimal',
    }


@contextlib.contextmanager
def managed_process(command: list[str], log_path: Path):
    with log_path.open('ab') as log:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        try:
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def watch_parent(pid: int) -> None:
    """Also stop the server if the window process crashes or is killed."""
    if sys.platform != 'win32':
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        raise RuntimeError('No se puede supervisar el proceso principal.')

    def wait():
        result = kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
        kernel.CloseHandle(handle)
        os._exit(0 if result == 0 else 1)

    threading.Thread(target=wait, daemon=True).start()


def wait_until_ready(process, port: int, timeout: float = 60) -> str:
    url = f'http://127.0.0.1:{port}'
    # Never send localhost readiness checks through a system proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('El servidor local no pudo arrancar. Consulta Datos/logs/server.log.')
        try:
            with opener.open(url + '/_stcore/health', timeout=0.5) as response:
                if response.status == 200 and response.read().strip() == b'ok':
                    return url
        except OSError:
            pass
        time.sleep(0.2)
    raise RuntimeError('La aplicación tardó demasiado en arrancar. Consulta Datos/logs/server.log.')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', type=int)
    parser.add_argument('--parent-pid', type=int)
    parser.add_argument('--self-test', action='store_true', help='Comprobar la ventana minimizada y salir.')
    args = parser.parse_args()
    frozen = bool(getattr(sys, 'frozen', False))
    root = Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parent
    resources = Path(getattr(sys, '_MEIPASS', root))
    data = root / 'Datos'
    for folder in ('logs', 'cache', 'Navegador', 'Proyectos', 'Exportaciones'):
        (data / folder).mkdir(parents=True, exist_ok=True)
    os.environ['PROXY_MAKER_DATA_DIR'] = str(data)
    os.chdir(root)
    log_name = 'server.log' if args.server else 'launcher.log'
    if sys.stdout is None:
        sys.stdout = (data / 'logs' / log_name).open('a', encoding='utf-8')
    if sys.stderr is None:
        sys.stderr = sys.stdout

    if args.server:
        if not args.parent_pid:
            raise RuntimeError('Falta el proceso principal.')
        watch_parent(args.parent_pid)
        from streamlit.web import bootstrap
        options = server_options(args.server)
        bootstrap.load_config_options(options)
        bootstrap.run(str(resources / 'app.py'), False, [], options)
        return 0

    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    command = [sys.executable]
    if not frozen:
        command.append(str(Path(__file__).resolve()))
    command.extend(['--server', str(port), '--parent-pid', str(os.getpid())])
    with managed_process(command, data / 'logs' / 'server.log') as process:
        print(f'Local server PID: {process.pid}', flush=True)
        url = wait_until_ready(process, port)
        print('Local server ready; loading WebView2', flush=True)
        import webview
        webview.settings['ALLOW_DOWNLOADS'] = True
        webview.settings['ALLOW_FILE_URLS'] = False
        window = webview.create_window(
            'Proxy Maker', url, width=1280, height=850, min_size=(960, 640),
            minimized=args.self_test, text_select=True,
        )
        result = {'ok': False}

        def verify_window():
            print('Window self-test started', flush=True)
            try:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    text = window.evaluate_js('document.body.innerText') or ''
                    if 'Proxy Maker' in text and 'Analizar mazo' in text:
                        result['ok'] = True
                        (data / 'logs' / 'self-test.txt').write_text('OK: WebView2 loaded Proxy Maker; Streamlit rendered the deck input.\n', encoding='utf-8')
                        break
                    time.sleep(0.5)
                if not result['ok']:
                    (data / 'logs' / 'self-test.txt').write_text('FAIL: window did not render the deck input.\n' + str(text), encoding='utf-8')
            finally:
                window.destroy()

        def on_start():
            # pywebview may leave a blank window when WebView2 initialization
            # fails instead of raising. Bound that failure and release the server.
            if not window.events.loaded.wait(45):
                (data / 'logs' / 'window-error.txt').write_text(
                    'WebView2 no terminó de cargar. Comprueba WebView2 Runtime y los permisos de Datos.\n',
                    encoding='utf-8',
                )
                window.destroy()
                return
            if args.self_test:
                verify_window()
            else:
                result['ok'] = True

        webview.start(
            func=on_start,
            gui='edgechromium', private_mode=False,
            storage_path=str(data / 'Navegador'),
        )
        if not result['ok']:
            raise RuntimeError('La ventana no pudo cargar. Consulta Datos/logs y comprueba WebView2 Runtime.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        traceback.print_exc()
        if '--server' not in sys.argv and '--self-test' not in sys.argv and sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                f'No se pudo abrir Proxy Maker.\n\n{exc}\n\nComprueba que la carpeta sea escribible y que Microsoft Edge WebView2 Runtime esté instalado.\nhttps://developer.microsoft.com/microsoft-edge/webview2/\n\nMás información en Datos\\logs.',
                'Proxy Maker', 0x10,
            )
        raise SystemExit(1)
