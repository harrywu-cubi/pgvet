import subprocess
import sys


def test_module_help_runs():
    result = subprocess.run(
        [sys.executable, "-m", "pgvet", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "pgvet" in result.stdout
