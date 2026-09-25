"""The commit-msg hook: a history that does not credit Claude, enforced rather than remembered."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".githooks" / "commit-msg"
"""The hook, as committed."""

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")


def verdict(message: str, tmp_path: Path) -> int:
    """Return the hook's exit status for a commit message."""
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text(message)
    return subprocess.run(["sh", str(HOOK), str(path)], capture_output=True, check=False).returncode


@pytest.mark.parametrize(
    "message",
    [
        "feat: a thing\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n",
        "fix: a thing\n\nco-authored-by: claude <noreply@anthropic.com>\n",
        "docs: a thing\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)\n",
        "chore: a thing\n\n  Co-Authored-By: Someone <noreply@anthropic.com>\n",
    ],
    ids=["trailer", "lower-case", "footer", "anthropic-address"],
)
def test_a_message_crediting_claude_is_refused(message: str, tmp_path: Path) -> None:
    """Whatever the case or the model name, the line does not enter the history."""
    assert verdict(message, tmp_path) == 1


@pytest.mark.parametrize(
    "message",
    [
        "feat(portfolio): a book keeps what it holds\n\nA body that mentions nothing.\n",
        "docs: explain why claude-style prompts are not used here\n",
        "fix: Co-Authored-By a colleague\n\nCo-Authored-By: A Colleague <colleague@example.com>\n",
    ],
    ids=["plain", "word-in-subject", "human-co-author"],
)
def test_an_ordinary_message_passes(message: str, tmp_path: Path) -> None:
    """The hook refuses one thing, and a human co-author is not it."""
    assert verdict(message, tmp_path) == 0


def test_the_hook_is_executable() -> None:
    """Git ignores a hook it cannot execute, silently."""
    assert HOOK.stat().st_mode & 0o111
