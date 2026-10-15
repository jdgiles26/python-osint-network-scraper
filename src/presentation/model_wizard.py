import queue
import threading
import tkinter as tk
from tkinter import filedialog

try:
    import ttkbootstrap as ttk
except ImportError:
    from tkinter import ttk

from src.application.packages import install_button_label, packages_for
from src.application.wizard import BACKEND_HELP, default_endpoint, fields_for, run_wizard_test
from src.domain.inference import BACKENDS, ModelConfig
from src.infrastructure.inference_factory import build_backend


def _mark(widget, testid: str):
    widget.testid = testid
    return widget


class ModelWizard(tk.Toplevel):
    """Three-step setup. A download waits until Confirm, then Test."""

    def __init__(self, master, on_saved=None, store_path=None):
        super().__init__(master)
        self.title("Model setup")
        self.geometry("680x640")
        self.minsize(560, 520)
        self._on_saved = on_saved
        self._store_path = store_path
        self.confirmed = False
        self._installing = False
        self._install_notes = queue.Queue()
        self.step = 1
        self.backend_var = tk.StringVar(value=BACKENDS[0])
        self.model_id_var = tk.StringVar()
        self.path_var = tk.StringVar()
        self.endpoint_var = tk.StringVar(value=default_endpoint(BACKENDS[0]))

        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)
        self.step_label = ttk.Label(frame, text="", font=("", 11, "bold"))
        self.step_label.pack(anchor="w")
        self.help_label = ttk.Label(frame, text="", wraplength=620, justify="left")
        self.help_label.pack(anchor="w", pady=(6, 12))

        self.backend_row = ttk.Frame(frame)
        ttk.Label(self.backend_row, text="How should the model run?").pack(anchor="w")
        backend = _mark(
            ttk.Combobox(self.backend_row, textvariable=self.backend_var, values=BACKENDS, state="readonly"),
            "wizard-backend",
        )
        backend.pack(fill="x", pady=(4, 0))
        backend.bind("<<ComboboxSelected>>", lambda _event: self._on_backend(apply_preset=True))

        self.model_row = ttk.Frame(frame, padding=8)
        ttk.Label(self.model_row, text="Hugging Face id, or the name Ollama already has.").pack(anchor="w")
        _mark(ttk.Entry(self.model_row, textvariable=self.model_id_var), "wizard-model-id").pack(fill="x", pady=(4, 0))

        self.path_row = ttk.Frame(frame, padding=8)
        ttk.Label(self.path_row, text="File or folder on this Mac").pack(anchor="w")
        path_line = ttk.Frame(self.path_row)
        path_line.pack(fill="x")
        _mark(ttk.Entry(path_line, textvariable=self.path_var), "wizard-path").pack(side="left", fill="x", expand=True)
        ttk.Button(path_line, text="Browse", command=self._browse).pack(side="left", padx=(8, 0))

        self.endpoint_row = ttk.Frame(frame, padding=8)
        ttk.Label(self.endpoint_row, text="Only used for Ollama and a llama.cpp server.").pack(anchor="w")
        _mark(ttk.Entry(self.endpoint_row, textvariable=self.endpoint_var), "wizard-endpoint").pack(fill="x", pady=(4, 0))

        self.actions = ttk.Frame(frame)
        self.actions.pack(fill="x", pady=16)
        self.back_btn = ttk.Button(self.actions, text="Back", command=self._back)
        self.back_btn.pack(side="left")
        self.next_btn = ttk.Button(self.actions, text="Next", command=self._next)
        self.next_btn.pack(side="left", padx=8)
        self.confirm_btn = ttk.Button(self.actions, text="Confirm", command=self._confirm)
        self.confirm_btn.pack(side="left")
        _mark(ttk.Button(self.actions, text="Test", command=self._test), "wizard-test").pack(side="left", padx=8)
        self.install_btn = _mark(ttk.Button(self.actions, text="", command=self._install), "wizard-install")
        self.install_btn.pack(side="right")

        self.result = _mark(ttk.Label(frame, text="Not tested.", wraplength=620, justify="left"), "wizard-result")
        self.result.pack(anchor="w", fill="x")
        self._on_backend()
        self._show_step()
        self.after(50, self._poll_install)

    def _on_backend(self, apply_preset=False):
        backend = self.backend_var.get().strip()
        self.help_label.configure(text=BACKEND_HELP.get(backend, "Choose a backend."))
        self.install_btn.configure(text=install_button_label(backend))
        if self._installing or not packages_for(backend):
            self.install_btn.configure(state="disabled")
        else:
            self.install_btn.configure(state="normal")
        preset = default_endpoint(backend)
        if apply_preset and preset:
            self.endpoint_var.set(preset)
        if apply_preset:
            self.confirmed = False
        needed = set(fields_for(backend))
        self.model_row.pack_forget()
        self.path_row.pack_forget()
        self.endpoint_row.pack_forget()
        if self.step == 1:
            return
        if "model_id" in needed:
            self.model_row.pack(fill="x", pady=(0, 8), before=self.actions)
        if "path" in needed:
            self.path_row.pack(fill="x", pady=(0, 8), before=self.actions)
        if "endpoint" in needed:
            self.endpoint_row.pack(fill="x", pady=(0, 8), before=self.actions)

    def _show_step(self):
        labels = {1: "Step 1 of 3 · Choose a backend", 2: "Step 2 of 3 · Point at the model", 3: "Step 3 of 3 · Confirm, then test"}
        self.step_label.configure(text=labels[self.step])
        if self.step == 1:
            self.backend_row.pack(fill="x", pady=(0, 8), before=self.actions)
        else:
            self.backend_row.pack_forget()
        self._on_backend()
        self.back_btn.configure(state="normal" if self.step > 1 else "disabled")
        self.next_btn.configure(state="normal" if self.step < 3 else "disabled")
        self.confirm_btn.configure(state="normal" if self.step == 3 else "disabled")

    def _next(self):
        self.step = min(3, self.step + 1)
        self._show_step()

    def _back(self):
        self.step = max(1, self.step - 1)
        self._show_step()

    def _browse(self):
        backend = self.backend_var.get()
        if backend in {"weights_dir", "mlx"}:
            path = filedialog.askdirectory(parent=self)
        elif backend == "onnx":
            path = filedialog.askopenfilename(parent=self, filetypes=[("ONNX", "*.onnx"), ("All files", "*.*")])
        elif backend in {"gguf_file", "llama_cpp"}:
            path = filedialog.askopenfilename(parent=self, filetypes=[("GGUF", "*.gguf"), ("All files", "*.*")])
        else:
            path = filedialog.askopenfilename(parent=self)
        if path:
            self.path_var.set(path)

    def _config(self) -> ModelConfig:
        return ModelConfig(
            self.backend_var.get().strip(),
            self.model_id_var.get().strip(),
            self.path_var.get().strip(),
            self.endpoint_var.get().strip(),
            confirmed=self.confirmed,
        )

    def _persist(self):
        config = self._config()
        if self._store_path:
            from src.infrastructure.model_store import save_model_config
            save_model_config(config, self._store_path)
        if self._on_saved:
            self._on_saved(config)

    def _confirm(self):
        self.confirmed = True
        self._persist()
        self.result.configure(text="Confirmed. Test now, or open AI chat and ask about the results. A Hugging Face download waits until a local generator is installed.")

    def _test(self):
        if self.step < 3:
            self.step = 3
            self._show_step()
        if self.confirmed:
            self._persist()
        self.result.configure(text=run_wizard_test(build_backend(self._config())))

    def _install(self):
        if self._installing:
            return
        packages = packages_for(self.backend_var.get().strip())
        if not packages:
            self.result.configure(text="Ollama and a llama.cpp server are separate apps. There is no Python library to install.")
            return
        self._installing = True
        self.install_btn.configure(state="disabled")
        self.result.configure(text=f"Installing {' + '.join(packages)}. This can take a few minutes.")

        def work():
            from src.infrastructure.pip_install import install_packages
            self._install_notes.put(install_packages(packages))

        threading.Thread(target=work, daemon=True).start()

    def _poll_install(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                ok, message = self._install_notes.get_nowait()
                self._installing = False
                self.result.configure(text=message)
                self._on_backend()
        except queue.Empty:
            pass
        self.after(50, self._poll_install)
