"""Publish a verified portable, preserving existing release assets."""
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


def find_release(tag: str) -> dict | None:
    validate_tag(tag)
    response = subprocess.run(
        ['gh', 'api', '--paginate', '--slurp', 'repos/{owner}/{repo}/releases'],
        check=True, capture_output=True, text=True,
    )
    # Authenticated listing includes drafts. Any API/JSON error fails closed.
    for page in json.loads(response.stdout):
        for release in page:
            if release['tag_name'] == tag:
                return release
    return None


def publish_release(tag: str, archive: Path) -> None:
    command = release_command(tag, archive)
    release = find_release(tag)
    if release is None:
        # Attach the ZIP before making the new release public.
        subprocess.run(command, check=True)
        draft = True
    else:
        if not any(asset['name'] == archive.name for asset in release['assets']):
            subprocess.run(['gh', 'release', 'upload', tag, str(archive)], check=True)
        else:
            print(f'{archive.name} ya existe; se conserva sin sobrescribir.')
        draft = release['draft']
    if draft:
        command = ['gh', 'release', 'edit', tag, '--draft=false']
        if '-' in tag:
            command.append('--prerelease')
        subprocess.run(command, check=True)


if __name__ == '__main__':
    tag = os.environ['RELEASE_TAG']
    publish_release(tag, Path('dist/ProxyMaker-Windows-portable.zip'))
