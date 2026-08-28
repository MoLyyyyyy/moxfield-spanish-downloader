"""Exercise the frozen server and real Streamlit protocol without external data."""
import os
from pathlib import Path
import socket
import sys
import urllib.request

from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from websockets.sync.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop import managed_process, wait_until_ready


def main():
    executable = Path(sys.argv[1]).resolve()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    with managed_process(
        [str(executable), '--server', str(port), '--parent-pid', str(os.getpid())],
        executable.parent / 'smoke-server.log',
    ) as process:
        url = wait_until_ready(process, port)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=5) as response:
            assert response.status == 200
            assert b'<html' in response.read()
        with connect(f'ws://127.0.0.1:{port}/_stcore/stream', origin=url, subprotocols=['streamlit'], proxy=None) as ws:
            request = BackMsg()
            request.rerun_script.SetInParent()
            ws.send(request.SerializeToString())
            rendered = []
            for _ in range(300):
                message = ForwardMsg()
                message.ParseFromString(ws.recv(timeout=30))
                if message.HasField('delta') and message.delta.HasField('new_element'):
                    element = message.delta.new_element
                    if element.HasField('exception'):
                        raise AssertionError(str(element.exception))
                rendered.append(str(message))
                if message.WhichOneof('type') == 'script_finished':
                    break
            text = '\n'.join(rendered)
            assert 'Proxy Maker' in text, text[-3000:]
            assert 'Analizar mazo' in text, text[-3000:]
            assert 'Lista del mazo' in text or 'Lista de cartas' in text or 'decklist_input' in text
        print('PASS: frozen server starts and renders the deck-input UI without Python installed in its folder.')
    with socket.socket() as probe:
        probe.settimeout(2)
        assert probe.connect_ex(('127.0.0.1', port)) != 0
    print('PASS: server stops and releases its local port.')


if __name__ == '__main__':
    main()
