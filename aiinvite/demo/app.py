"""Minimal, credible demo window: chat, vault, export, model switch."""
from __future__ import annotations

import pathlib
import sys
import threading

LABELS = {
    "title": "AI Invite · Memory — 最小可信演示",
    "send": "发送",
    "export": "导出人格",
    "import": "导入人格",
    "verify": "校验证据链",
    "switch": "换模型（同一份记忆）",
    "vault": "人格保险箱",
    "kid": "身份 kid",
    "events": "证据条数",
    "model": "当前模型",
    "card": "用户卡",
    "traits": "特质",
    "you": "你",
    "ai": "它",
    "refused": "【闸门拒绝】",
    "where": "记忆目录",
    "hint": "说一句话，然后按「换模型」再问一次——看它是不是还是它。",
}


def build(engine, labels=None):
    """Build the window; imported lazily so headless imports stay possible."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext

    labels = labels or LABELS
    root = tk.Tk()
    root.title(labels["title"])
    root.geometry("980x640")

    top = tk.Frame(root)
    top.pack(fill="x", padx=8, pady=6)
    model_var = tk.StringVar(value=engine.model)

    tk.Label(top, text=labels["model"]).pack(side="left")
    tk.Entry(top, textvariable=model_var, width=18).pack(side="left", padx=4)

    chat = scrolledtext.ScrolledText(root, height=18, wrap="word")
    chat.pack(fill="both", expand=True, padx=8, pady=4)
    chat.insert("end", labels["hint"] + chr(10))
    chat.configure(state="disabled")

    bottom = tk.Frame(root)
    bottom.pack(fill="x", padx=8, pady=4)
    entry = tk.Entry(bottom)
    entry.pack(side="left", fill="x", expand=True)

    side = tk.Frame(root, width=320)
    side.pack(fill="y", side="right", padx=8, pady=6)
    vault = tk.Text(side, width=42, height=26, wrap="word")
    vault.pack(fill="both", expand=True)
    vault.configure(state="disabled")

    def append(text):
        chat.configure(state="normal")
        chat.insert("end", text + chr(10))
        chat.see("end")
        chat.configure(state="disabled")

    def refresh():
        snap = engine.snapshot()
        lines = [
            labels["vault"],
            "",
            labels["kid"] + ": " + (snap["kid"][:24] or "-"),
            labels["events"] + ": " + str(snap["events"]),
            labels["model"] + ": " + snap["model"],
            "",
            labels["card"] + ":",
            snap["card"] or "-",
            "",
            labels["traits"] + ": " + (", ".join(snap["traits"]) or "-"),
            "",
            labels["where"] + ":",
            snap["store"],
        ]
        vault.configure(state="normal")
        vault.delete("1.0", "end")
        vault.insert("end", chr(10).join(lines))
        vault.configure(state="disabled")

    def work():
        text = entry.get().strip()
        if not text:
            return
        entry.delete(0, "end")
        append(labels["you"] + ": " + text)
        refresh()

        def run():
            try:
                turn = engine.send(text)
                prefix = labels["refused"] if turn.refused else labels["ai"]
                append(prefix + ": " + turn.text)
            except Exception as error:  # noqa: BLE001 - the window must stay alive
                append("[error] " + str(error))
            finally:
                root.after(0, refresh)

        threading.Thread(target=run, daemon=True).start()

    def do_switch():
        result = engine.switch_model(model_var.get().strip())
        refresh()
        same = result["kid_before"] == result["kid_after"]
        append("[model] -> " + engine.model)
        append("[kid] " + result["kid_after"][:24] + (" (unchanged)" if same else " (CHANGED!)"))

    def do_export():
        target = filedialog.askdirectory(title=labels["export"])
        if not target:
            return
        path = pathlib.Path(target) / "aiinvite-persona"
        try:
            engine.export_to(path)
            append("[export] " + str(path))
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("export", str(error))

    def do_import():
        source = filedialog.askdirectory(title=labels["import"])
        if not source:
            return
        try:
            engine.import_from(source)
            append("[import] " + source)
            refresh()
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("import", str(error))

    def do_verify():
        try:
            count = engine.verify()
            append("[verify] ok, " + str(count) + " events")
        except Exception as error:  # noqa: BLE001
            append("[verify] FAILED: " + str(error))

    tk.Button(bottom, text=labels["send"], command=work).pack(side="left", padx=4)
    tk.Button(top, text=labels["switch"], command=do_switch).pack(side="left", padx=8)
    tk.Button(side, text=labels["export"], command=do_export).pack(fill="x", pady=2)
    tk.Button(side, text=labels["import"], command=do_import).pack(fill="x", pady=2)
    tk.Button(side, text=labels["verify"], command=do_verify).pack(fill="x", pady=2)

    entry.bind("<Return>", lambda _event: work())
    refresh()
    return root


def main(argv=None):
    """Open the demo window."""
    from aiinvite.demo.engine import DEFAULT_MODEL, DemoEngine, default_store

    argv = list(sys.argv[1:] if argv is None else argv)
    store = pathlib.Path(argv[0]) if argv else default_store()
    model = argv[1] if len(argv) > 1 else DEFAULT_MODEL
    engine = DemoEngine(store, model=model)
    build(engine).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
