from importlib.metadata import version as installed_version

from tooru import APP_VERSION, __version__
from tooru.core.config import Settings
from tooru.version import display_version


def test_all_runtime_versions_have_one_source() -> None:
    assert installed_version("dragon-tory") == __version__
    assert display_version(__version__) == APP_VERSION
    assert Settings().version == APP_VERSION


def test_display_version_format() -> None:
    assert display_version("0.0.4") == "00.00.04"
    assert display_version("1.12.7") == "01.12.07"
