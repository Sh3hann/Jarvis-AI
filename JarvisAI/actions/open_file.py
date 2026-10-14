"""
Action to open files, folders, documents, or File Explorer in system applications.
"""
from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from actions.file_controller import (
    _get_desktop,
    _get_documents,
    _get_downloads,
    _get_pictures,
    _resolve_path,
)

_OS = platform.system()


def open_file_or_folder(
    path: str = "",
    name: str = "",
    folder: str = "",
    show_in_folder: bool = False,
) -> str:
    """Open a file or folder in its default system application or File Explorer."""
    path_str = str(path or "").strip()
    name_str = str(name or "").strip()
    folder_str = str(folder or "").strip()

    # Case 1: Generic File Explorer / Finder request
    if (not path_str and not name_str) or path_str.lower() in ("explorer", "file explorer", "files", "file_explorer"):
        if _OS == "Windows":
            subprocess.Popen(["explorer.exe"])
            return "File Explorer opened."
        elif _OS == "Darwin":
            subprocess.Popen(["open", str(Path.home())])
            return "Finder opened."
        else:
            subprocess.Popen(["xdg-open", str(Path.home())])
            return "File manager opened."

    target: Path | None = None

    # Case 2: Named file or path resolution
    query = name_str or path_str
    if query:
        # Check direct path first
        candidate = _resolve_path(query)
        if candidate.exists():
            target = candidate
        elif folder_str:
            f_dir = _resolve_path(folder_str)
            if (f_dir / query).exists():
                target = f_dir / query

        if not target or not target.exists():
            # Search common directories
            search_dirs = [
                _get_downloads(),
                _get_desktop(),
                _get_documents(),
                _get_pictures(),
                Path.home(),
                Path.cwd(),
            ]
            for search_dir in search_dirs:
                try:
                    matches = [
                        p for p in search_dir.iterdir()
                        if query.lower() in p.name.lower()
                    ]
                    if matches:
                        target = matches[0]
                        break
                except Exception:
                    continue

    if not target or not target.exists():
        return f"File or folder '{query}' not found."

    # Avoid opening sensitive credential/key files
    try:
        from core import path_guard
        if path_guard.protected_reason(target, write=False):
            return f"Access denied: protected file {target.name}"
    except Exception:
        pass

    try:
        if _OS == "Windows":
            if target.is_dir() or show_in_folder:
                if show_in_folder and target.is_file():
                    subprocess.Popen(f'explorer.exe /select,"{str(target)}"')
                else:
                    subprocess.Popen(["explorer.exe", str(target)])
            else:
                try:
                    os.startfile(str(target))
                except Exception:
                    subprocess.Popen(f'start "" "{str(target)}"', shell=True)
        elif _OS == "Darwin":
            if show_in_folder:
                subprocess.Popen(["open", "-R", str(target)])
            else:
                subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target.parent if show_in_folder else target)])

        kind = "Folder" if target.is_dir() else "File"
        return f"Opened {kind.lower()}: {target.name}"
    except Exception as e:
        return f"Failed to open '{target.name}': {e}"


def open_file_handler(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    path = params.get("path", "")
    name = params.get("name", "")
    folder = params.get("folder", "")
    show_in_folder = bool(params.get("show_in_folder", False))

    if player:
        player.write_log(f"[open_file] {name or path or 'explorer'}")

    return open_file_or_folder(path=path, name=name, folder=folder, show_in_folder=show_in_folder)


TOOL = {
    "name": "open_file",
    "description": (
        "Opens any file, folder, document, or File Explorer in its default application or Explorer window. "
        "Call this whenever the user says 'open this file', 'open that file', 'open file explorer', 'open my downloads', "
        "'open [filename]', or wants to view or launch a file on screen."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "path": {
                "type": "STRING",
                "description": "Path or shortcut (e.g. desktop, downloads, documents, explorer, or file path)."
            },
            "name": {
                "type": "STRING",
                "description": "Name or keyword of the file/folder to find and open (e.g. report.pdf, notes.txt, resume)."
            },
            "folder": {
                "type": "STRING",
                "description": "Optional directory to look in (e.g. downloads, desktop, documents)."
            },
            "show_in_folder": {
                "type": "BOOLEAN",
                "description": "If True, opens File Explorer and highlights the file instead of launching it directly."
            }
        }
    },
    "handler": open_file_handler,
}
