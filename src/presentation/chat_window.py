"""One chat for the current results, saved sessions, and the next tool to run."""
import queue
import threading
import tkinter as tk
from tkinter import scrolledtext

from src.domain.chat import ChatReply

try:
    import ttkbootstrap as ttk
except ImportError:
    from tkinter import ttk


class ChatWindow(tk.Toplevel):
    """Ask about results. Option buttons call search, scrape, or watch."""

    def __init__(self, master, ask, run_action, opening, backend_label: str, before_ask=None, install_libraries=None):
        super().__init__(master)
        self.title("AI chat")
        self.geometry("760x680")
        self.minsize(560, 480)
        self._ask = ask
        self._run_action = run_action
        self._before_ask = before_ask
        self._install_libraries = install_libraries
        self._busy = False
        self._history = []
        self._option_buttons = []
        self._inbox = queue.Queue()

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="AI chat", font=("Helvetica", 14, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text=backend_label,
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(2, 8))
        ttk.Label(
            frame,
            text="Ask about the rows on screen and the crawls saved in History. A choice below runs a deeper search, a scrape, or a watch.",
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        if install_libraries is not None:
            ttk.Button(frame, text="Install libraries", command=self._install_libraries_clicked).pack(anchor="w", pady=(0, 8))

        self.transcript = scrolledtext.ScrolledText(frame, height=16, wrap="word", state="disabled")
        self.transcript.pack(fill="both", expand=True)

        self.options = ttk.Frame(frame, padding=(0, 8, 0, 0))
        self.options.pack(fill="x")

        entry_row = ttk.Frame(frame, padding=(0, 8, 0, 0))
        entry_row.pack(fill="x")
        self.input_var = tk.StringVar()
        entry = ttk.Entry(entry_row, textvariable=self.input_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _event: self._send())
        self.send_btn = ttk.Button(entry_row, text="Send", command=self._send)
        self.send_btn.pack(side="left", padx=(8, 0))
        self._show_reply(opening)
        self.after(50, self._poll)

    def _show_reply(self, reply):
        self._append("Assistant", reply.text)
        self._set_actions(reply.actions)
        self._busy = False
        self.send_btn.configure(state="normal")

    def _append(self, who: str, text: str):
        self.transcript.configure(state="normal")
        self.transcript.insert("end", f"{who}: {text}\n\n")
        self.transcript.see("end")
        self.transcript.configure(state="disabled")

    def _set_actions(self, actions):
        for child in self.options.winfo_children():
            child.destroy()
        self._option_buttons = []
        if not actions:
            ttk.Label(self.options, text="No follow-up yet. Ask about a person, place, or page in the results.").pack(anchor="w")
            return
        ttk.Label(self.options, text="Next step").pack(anchor="w", pady=(0, 4))
        for action in list(actions)[:6]:
            button = ttk.Button(
                self.options,
                text=action.label,
                command=lambda action=action: self._choose(action),
            )
            button.pack(fill="x", pady=2)
            self._option_buttons.append(button)

    def _send(self):
        question = self.input_var.get().strip()
        if not question or self._busy:
            return
        self._busy = True
        self.send_btn.configure(state="disabled")
        self.input_var.set("")
        self._append("You", question)
        if self._before_ask:
            self._before_ask()
        history = list(self._history)
        self._history.append({"role": "user", "text": question})

        def work():
            try:
                reply = self._ask(question, history)
            except Exception as exc:
                reply = ChatReply(f"The model could not be asked: {exc}", ())
            self._inbox.put(reply)

        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                self._finish(self._inbox.get_nowait())
        except queue.Empty:
            pass
        self.after(50, self._poll)

    def _finish(self, reply):
        if not self.winfo_exists():
            return
        self._history.append({"role": "assistant", "text": reply.text})
        self._show_reply(reply)

    def _install_libraries_clicked(self):
        try:
            message = self._install_libraries()
        except Exception as exc:
            message = f"Could not install the libraries: {exc}"
        self._append("Assistant", message or "Installing the model libraries.")

    def _choose(self, action):
        try:
            message = self._run_action(action)
        except Exception as exc:
            message = f"Could not run that step: {exc}"
        self._append("Assistant", message or "Done.")
