"""A harmless window for manual and end-to-end tests: counts clicks and double-clicks.

Every change is also printed to stdout as one JSON line, so test scripts can read it."""

import json
import sys
import tkinter as tk

TITLE = "ai-desktop クリック試験"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    counts = {"single": 0, "double": 0}
    root = tk.Tk()
    root.title(TITLE)
    root.geometry("520x320+240+240")
    label = tk.Label(root, font=("Yu Gothic UI", 20), bg="#f4f4f4")
    label.pack(expand=True, fill="both")

    def show() -> None:
        label.config(text=f"クリック: {counts['single']}\nダブルクリック: {counts['double']}")
        print(json.dumps(counts), flush=True)

    def on_click(_event: tk.Event) -> None:
        counts["single"] += 1
        show()

    def on_double(_event: tk.Event) -> None:
        counts["double"] += 1
        show()

    label.bind("<Button-1>", on_click)
    label.bind("<Double-Button-1>", on_double)
    show()
    root.mainloop()


if __name__ == "__main__":
    main()
