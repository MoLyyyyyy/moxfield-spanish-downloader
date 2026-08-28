"""Create a draft only; never replace assets or publish an existing release."""
import os
import json
from pathlib import Path
import re
import subprocess


def validate_tag(tag: str) -> None:
    if not re.fullmatch(r'v\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?', tag):
        raise ValueError('Usa una etiqueta como v1.2.3 o v1.2.3-beta.1.')


def release_command(tag: str, archive: Path) -> list[str]:
    validate_tag(tag)
    if not archive.is_file():
        raise FileNotFoundError(archive)
    command = [
        'gh', 'release', 'create', tag, str(archive),
        '--draft', '--verify-tag', '--generate-notes',
        '--title', f'Proxy Maker {tag}',
    ]
    if '-' in tag:
        command.append('--prerelease')
    return command


def ensure_release_absent(tag: str) -> None:
    validate_tag(tag)
    response = subprocess.run(
        ['gh', 'api', '--paginate', '--slurp', 'repos/{owner}/{repo}/releases'],
        check=True, capture_output=True, text=True,
    )
    # Authenticated listing includes drafts. Any API/JSON error fails closed.
    for page in json.loads(response.stdout):
        for release in page:
            if release['tag_name'] == tag:
                raise ValueError(f'La release {tag} ya existe; no se modificará.')


if __name__ == '__main__':
    tag = os.environ['RELEASE_TAG']
    command = release_command(tag, Path('dist/ProxyMaker-Windows-portable.zip'))
    ensure_release_absent(tag)
    subprocess.run(command, check=True)
