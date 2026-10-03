"""Manual smoke test: enumerate and capture on the real desktop, saving to smoke-out/."""

import sys
from pathlib import Path

from ai_desktop import capture


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    capture.enable_dpi_awareness()
    out = Path(__file__).resolve().parent.parent / "smoke-out"
    out.mkdir(exist_ok=True)

    for monitor in capture.list_monitors():
        print("monitor:", monitor)

    windows = capture.list_windows()
    print(f"windows: {len(windows)} visible")
    for window in windows[:10]:
        print("  ", window)

    image, monitor = capture.capture_monitor(None)
    image.save(out / "monitor.png")
    print("captured monitor", monitor.id, image.size, image.getextrema())

    target = next(w for w in windows if not w.minimized and w.width > 100 and w.height > 100)
    image, window = capture.capture_window(target.id)
    image.save(out / "window.png")
    print("captured window", repr(window.title), image.size, image.getextrema())


if __name__ == "__main__":
    main()
