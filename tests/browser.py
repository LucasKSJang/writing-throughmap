"""Headless Chrome or Edge for the page tests: find a browser, read a page's DOM, take a screenshot.

Every run starts the browser with a new, empty profile in a temporary folder (--user-data-dir), so
it never touches the profile of a browser that is open on the desktop, and the folder is deleted
when the run ends.
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BROWSER_ENV = "THROUGHMAP_BROWSER"   # a browser's path or command name, tried before any other
_DUMP_HEIGHT = 2400
# Blink's setting for the colour scheme a page sees through prefers-color-scheme: 0 is dark.
_COLOR_SCHEMES = {"dark": "0", "light": "1"}
_VIRTUAL_TIME_BUDGET_MS = 4000       # virtual time: the page's timers run without real waiting
_TIMEOUT_SECONDS = 120

# Command names on PATH, Chrome's first. Chromium counts as Chrome: it is what Linux tends to have.
_COMMANDS = {
    "chrome": ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"),
    "edge": ("microsoft-edge", "microsoft-edge-stable", "msedge"),
}


def _standard_paths(browser: str) -> list[str]:
    """Return where ``browser`` ("chrome" or "edge") installs itself on this operating system."""
    if sys.platform == "win32":
        parts = {"chrome": ("Google", "Chrome", "Application", "chrome.exe"),
                 "edge": ("Microsoft", "Edge", "Application", "msedge.exe")}[browser]
        roots = (os.environ.get(name) for name in ("PROGRAMFILES", "PROGRAMFILES(X86)",
                                                    "LOCALAPPDATA"))
        return [os.path.join(root, *parts) for root in roots if root]
    if sys.platform == "darwin":
        app = {"chrome": "Google Chrome", "edge": "Microsoft Edge"}[browser]
        inside = f"{app}.app/Contents/MacOS/{app}"
        return [f"/Applications/{inside}", os.path.expanduser(f"~/Applications/{inside}")]
    return {"chrome": ["/opt/google/chrome/chrome"],
            "edge": ["/opt/microsoft/msedge/msedge"]}[browser]


def find_browser() -> str | None:
    """Return the path of the browser the page tests use, or None when there is none.

    THROUGHMAP_BROWSER comes first, as a path or a command on PATH. It is returned even when nothing
    is there, so that a wrong setting makes the tests fail instead of skipping them. Then Chrome
    and then Edge, each at its standard install paths on Windows, macOS or Linux and then on PATH.
    """
    chosen = os.environ.get(BROWSER_ENV, "").strip()
    if chosen:
        return shutil.which(chosen) or chosen
    for browser in ("chrome", "edge"):
        for path in _standard_paths(browser):
            if os.path.isfile(path):
                return path
        for command in _COMMANDS[browser]:
            found = shutil.which(command)
            if found:
                return found
    return None


def _page_uri(html_path, hash: str) -> str:
    uri = Path(html_path).resolve().as_uri()
    return f"{uri}#{hash}" if hash else uri


def _remove_profile(folder: str) -> None:
    """Delete a temporary profile. Windows can hold its files a moment after the browser exits."""
    for _ in range(20):
        shutil.rmtree(folder, ignore_errors=True)
        if not os.path.exists(folder):
            return
        time.sleep(0.1)
    atexit.register(shutil.rmtree, folder, ignore_errors=True)


def _scheme_arguments(color_scheme: str) -> list[str]:
    """Return the switch that makes pages see ``color_scheme``; none for "" (the system's)."""
    if not color_scheme:
        return []
    return [f"--blink-settings=preferredColorScheme={_COLOR_SCHEMES[color_scheme]}"]


def _run_headless(arguments: list[str]) -> bytes:
    """Run the browser headless with a fresh profile and ``arguments``; return what it printed."""
    browser = find_browser()
    if browser is None:
        raise RuntimeError(f"no Chrome or Edge found: set {BROWSER_ENV} to a browser")
    profile = tempfile.mkdtemp(prefix="throughmap-browser-")
    try:
        done = subprocess.run(
            [browser, "--headless=new", "--disable-gpu", "--no-first-run",
             f"--user-data-dir={profile}", f"--virtual-time-budget={_VIRTUAL_TIME_BUDGET_MS}",
             *arguments],
            capture_output=True, stdin=subprocess.DEVNULL, timeout=_TIMEOUT_SECONDS)
    finally:
        _remove_profile(profile)
    if done.returncode != 0:
        errors = done.stderr.decode("utf-8", "replace").strip()[-2000:]
        raise RuntimeError(f"{browser} exited with {done.returncode}: {errors}")
    return done.stdout


def dump_dom(html_path, hash: str = "", width: int = 1240, color_scheme: str = "") -> str:
    """Open a page headless and return its DOM, serialized, once its scripts have run.

    ``hash`` is the fragment without its "#", such as "select=P2". The window is ``width`` by 2400
    pixels; the browser keeps a few of them for its frame and the scroll bar. ``color_scheme``,
    "light" or "dark", is what the page sees as the preferred scheme; "" leaves the system's.
    """
    printed = _run_headless([f"--window-size={width},{_DUMP_HEIGHT}",
                             *_scheme_arguments(color_scheme), "--dump-dom",
                             _page_uri(html_path, hash)])
    return printed.decode("utf-8")


def screenshot(html_path, png_path, hash: str = "", width: int = 1240, height: int = 2400,
               scale: int = 2, color_scheme: str = "") -> None:
    """Open a page headless and save the top ``width`` by ``height`` pixels of it as a PNG.

    ``scale`` is the device pixel ratio, so the image is ``scale`` times as wide and as high.
    ``color_scheme`` is as for dump_dom. Raises RuntimeError when the browser fails or writes no
    file.
    """
    target = Path(png_path).resolve()
    target.unlink(missing_ok=True)       # so that an old image cannot pass for a new one
    _run_headless([f"--window-size={width},{height}", f"--force-device-scale-factor={scale}",
                   "--hide-scrollbars", *_scheme_arguments(color_scheme),
                   f"--screenshot={target}", _page_uri(html_path, hash)])
    if not target.is_file():
        raise RuntimeError(f"the browser wrote no screenshot at {target}")
