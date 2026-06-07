"""``clean-ide`` — launch a tmux session: editor pane + clean-tree sidebar.

One command opens an IDE-style layout in any terminal that can run tmux: the
main pane runs your editor; a narrow right pane runs ``clean-tree --sidebar``.
Pressing Enter on a file in the sidebar opens it in the editor pane. Quitting
the sidebar (``q``) or the editor tears the whole session down. tmux is required
but stays invisible — you only ever run ``clean-ide``.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys

_SIDEBAR_WIDTH = "40"  # columns for the right-hand tree pane (pinned on resize)


def _require_tmux() -> None:
    if shutil.which("tmux") is None:
        sys.exit(
            "clean-ide needs tmux (it stays hidden). Install it with:\n"
            "  brew install tmux   # macOS\n"
            "  apt install tmux    # Debian/Ubuntu\n"
        )


def _editor_command(editor: str) -> list[str]:
    """Run *editor* via ``sh -c`` so compound values (e.g. 'code --wait') work."""
    return ["sh", "-c", editor]


def _sidebar_command(python: str, editor_pane: str, session: str) -> str:
    """Shell command for the sidebar pane: run the explorer in --sidebar mode
    with the editor pane id (open target) and session name (quit target)."""
    run = f"{shlex.quote(python)} -m clean.scoring.explorer --sidebar"
    return (
        f"CLEAN_TREE_TARGET={editor_pane} "
        f"CLEAN_IDE_SESSION={shlex.quote(session)} {run}"
    )


def main() -> None:
    _require_tmux()
    cwd = os.getcwd()
    editor = os.environ.get("EDITOR") or "vim"
    session = f"clean-ide-{os.getpid()}"

    # Main pane runs the editor (via sh -c so compound $EDITOR values work).
    subprocess.run(
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            session,
            "-c",
            cwd,
            *_editor_command(editor),
        ],
        check=True,
    )
    try:
        editor_pane = subprocess.run(
            ["tmux", "list-panes", "-t", session, "-F", "#{pane_id}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        # Narrow right pane runs the sidebar, told which pane to open files into.
        # -P -F captures the new pane's id so we can pin its width.
        sidebar_pane = subprocess.run(
            [
                "tmux",
                "split-window",
                "-h",
                "-l",
                _SIDEBAR_WIDTH,
                "-t",
                session,
                "-c",
                cwd,
                "-P",
                "-F",
                "#{pane_id}",
                _sidebar_command(sys.executable, editor_pane, session),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        # Don't leave a half-built detached session orphaned.
        subprocess.run(["tmux", "kill-session", "-t", session], check=False)
        raise

    # Niceties: click-to-focus panes; hide the tmux status bar; start in editor.
    for opt in (["mouse", "on"], ["status", "off"]):
        subprocess.run(["tmux", "set-option", "-t", session, *opt], check=False)
    # Keep the sidebar pinned narrow when the window is resized (so the editor
    # stays wide and the tree never balloons past its tree-only width).
    subprocess.run(
        [
            "tmux",
            "set-hook",
            "-t",
            session,
            "window-resized",
            f"resize-pane -t {sidebar_pane} -x {_SIDEBAR_WIDTH}",
        ],
        check=False,
    )
    subprocess.run(["tmux", "select-pane", "-t", editor_pane], check=False)

    # Replace this process with the attached session (blocks until it ends).
    os.execvp("tmux", ["tmux", "attach-session", "-t", session])


if __name__ == "__main__":
    main()
