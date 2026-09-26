"""The store is POSIX-only, and says so on native Windows (decision D11).

Native Windows cannot be run here; what can be checked is the one line that
decides, in a process of its own told it is on Windows.
"""

from __future__ import annotations

import subprocess
import sys


def test_importing_the_store_on_native_windows_fails_with_a_message_that_says_what_to_do() -> None:
    """Audit R01: the import used to die on ``No module named 'fcntl'``."""
    probe = (
        "import sys\n"
        "sys.platform = 'win32'\n"
        "try:\n"
        "    import quant_backtester.data.repository\n"
        "except ImportError as error:\n"
        "    print(error)\n"
        "    raise SystemExit(3)\n"
    )

    ran = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=False)

    assert ran.returncode == 3
    assert "POSIX" in ran.stdout
    assert "WSL" in ran.stdout


def test_the_store_imports_on_this_platform() -> None:
    import quant_backtester.data.repository as repository

    assert repository.LOCK_FILE == ".lock"
