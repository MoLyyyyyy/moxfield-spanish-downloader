import pytest
import json
import subprocess


def test_release_command_attaches_zip_as_draft(tmp_path):
    from tools.release_portable import release_command

    archive = tmp_path / 'portable with spaces.zip'
    archive.write_bytes(b'archive')
    command = release_command('v1.2.3', archive)
    assert command == [
        'gh', 'release', 'create', 'v1.2.3', str(archive),
        '--draft', '--verify-tag', '--generate-notes',
        '--title', 'Proxy Maker v1.2.3',
    ]


def test_beta_release_is_marked_prerelease(tmp_path):
    from tools.release_portable import release_command

    archive = tmp_path / 'portable.zip'
    archive.touch()
    assert '--prerelease' in release_command('v1.0.0-beta.1', archive)


@pytest.mark.parametrize('tag', ['', 'main', '--draft', 'v1.0', 'v1.0.0;echo hacked', 'v1.0.0\n'])
def test_invalid_tag_is_rejected_before_any_release(tag, tmp_path):
    from tools.release_portable import release_command

    archive = tmp_path / 'portable.zip'
    archive.touch()
    with pytest.raises(ValueError):
        release_command(tag, archive)


def test_missing_archive_cannot_create_an_empty_release(tmp_path):
    from tools.release_portable import release_command

    with pytest.raises(FileNotFoundError):
        release_command('v1.2.3', tmp_path / 'missing.zip')


@pytest.mark.parametrize('draft', [False, True])
def test_existing_release_is_rejected_even_on_a_later_page(monkeypatch, draft):
    from tools.release_portable import ensure_release_absent

    def api(command, **kwargs):
        assert command == ['gh', 'api', '--paginate', '--slurp', 'repos/{owner}/{repo}/releases']
        assert kwargs['check'] is True
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps([
            [{'tag_name': 'v0.1.0', 'draft': False}],
            [{'tag_name': 'v1.2.3', 'draft': draft}],
        ]))

    monkeypatch.setattr(subprocess, 'run', api)
    with pytest.raises(ValueError, match='ya existe'):
        ensure_release_absent('v1.2.3')


def test_release_lookup_errors_are_not_treated_as_absence(monkeypatch):
    from tools.release_portable import ensure_release_absent

    def unavailable(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr='API unavailable')

    monkeypatch.setattr(subprocess, 'run', unavailable)
    with pytest.raises(subprocess.CalledProcessError):
        ensure_release_absent('v1.2.3')


def test_unused_tag_passes_existing_release_check(monkeypatch):
    from tools.release_portable import ensure_release_absent

    monkeypatch.setattr(subprocess, 'run', lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 0, stdout='[[{"tag_name":"v0.1.0"}]]'))
    ensure_release_absent('v1.2.3')
