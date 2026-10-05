"""A harmless window for manual and end-to-end tests: counts clicks, double-clicks and hovers.

Turns yellow while the cursor is on it. Every change is also printed to stdout as one JSON
line, so test scripts can read it. An optional first argument sets the tkinter geometry."""

import json
import sys
import tkinter as tk

TITLE = "ai-desktop クリック試験"
DEFAULT_GEOMETRY = "520x320+240+240"
IDLE_COLOR = "#f4f4f4"
HOVER_COLOR = "#ffe066"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    counts = {"single": 0, "double": 0, "enter": 0, "leave": 0}
    root = tk.Tk()
    root.title(TITLE)
    root.geometry(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GEOMETRY)
    label = tk.Label(root, font=("Yu Gothic UI", 20), bg=IDLE_COLOR)
    label.pack(expand=True, fill="both")

    def show() -> None:
        label.config(
            text=f"クリック: {counts['single']}\nダブルクリック: {counts['double']}\n"
            f"ホバー: {counts['enter']} / {counts['leave']}"
        )
        print(json.dumps(counts), flush=True)

    def count(name: str, color: str | None = None):
        def handler(_event: tk.Event) -> None:
            counts[name] += 1
            if color is not None:
                label.config(bg=color)
            show()

        return handler

    label.bind("<Button-1>", count("single"))
    label.bind("<Double-Button-1>", count("double"))
    label.bind("<Enter>", count("enter", HOVER_COLOR))
    label.bind("<Leave>", count("leave", IDLE_COLOR))
    show()
    root.mainloop()


if __name__ == "__main__":
    main()
