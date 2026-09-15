from pathlib import Path
import importlib
import pkgutil

from oceanography.cli import initialize_workspace, main
from oceanography.config import load


def test_external_workspace_and_non_overwriting_init(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(['init']) == 0
    doc, cfg = load()
    assert doc.resolve_path(cfg.raw_dir) == tmp_path / cfg.raw_dir
    config = tmp_path / 'config/data/environment_oceanographic.yaml'
    config.write_text(config.read_text() + '\n# user configuration\n')
    assert initialize_workspace(tmp_path) == []
    assert config.read_text().endswith('# user configuration\n')


def test_workspace_override_restored(tmp_path, monkeypatch):
    monkeypatch.setenv('OCEANOGRAPHY_WORKSPACE', str(tmp_path / 'original'))
    main(['init', '--workspace', str(tmp_path / 'selected')])
    from oceanography.core.config.paths import project_root
    assert project_root() == tmp_path / 'original'
    assert (tmp_path / 'selected/config/common.yaml').exists()


def test_packaged_templates_match_checkout():
    root = Path(__file__).resolve().parents[1]
    for source in (root / 'config').rglob('*.yaml'):
        assert source.read_bytes() == (root / 'src/oceanography/resources' / source.relative_to(root)).read_bytes()


def test_imports_are_application_independent(monkeypatch):
    import sys
    class RejectOrcaCast:
        def find_spec(self, name, *args):
            if name == 'orcacast' or name.startswith('orcacast.'):
                raise AssertionError(name)
    monkeypatch.setattr(sys, 'meta_path', [RejectOrcaCast(), *sys.meta_path])
    import oceanography
    for module in pkgutil.walk_packages(oceanography.__path__, 'oceanography.'):
        importlib.import_module(module.name)
