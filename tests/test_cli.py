import tomllib

from harness_lib import ROOT
from respectful_offers import __version__
from respectful_offers.cli import main


def test_cli_version_flag_prints_version(capsys):
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    assert capsys.readouterr().out.strip() == f"offers {__version__}"


def test_pyproject_metadata():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert meta["name"] == "respectful-offers"
    assert meta["requires-python"] == ">=3.11"
    assert meta["license"] == "MIT"
    assert meta["scripts"]["offers"] == "respectful_offers.cli:main"
    assert meta["version"] == __version__
