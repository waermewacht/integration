"""tools/make_strings.py must reproduce the translation files.

The files were edited by hand after 0.2 and the generator fell behind;
running it would have dropped texts. Change the generator, then run it.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
FILES = ("strings.json", "icons.json", "translations/en.json", "translations/de.json")


def test_generator_matches_files(tmp_path: Path) -> None:
    out = tmp_path / "custom_components" / "waermewacht"
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "make_strings.py"), str(tmp_path)],
        check=True,
        capture_output=True,
    )
    component = ROOT / "custom_components" / "waermewacht"
    for name in FILES:
        generated = (out / name).read_text(encoding="utf-8")
        assert generated == (component / name).read_text(encoding="utf-8"), name
