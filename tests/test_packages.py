import subprocess
import sys

import src.infrastructure.pip_install as pip_install
from src.application.packages import install_button_label, packages_for


def test_each_backend_lists_only_its_libraries():
    assert packages_for("huggingface") == ("huggingface_hub", "transformers")
    assert packages_for("weights_dir") == ("huggingface_hub", "transformers")
    assert packages_for("llama_cpp") == ("llama-cpp-python",)
    assert packages_for("gguf_file") == ("llama-cpp-python",)
    assert packages_for("mlx") == ("mlx-lm",)
    assert packages_for("onnx") == ("onnxruntime",)
    assert packages_for("ollama") == ()
    assert packages_for("llamacpp_server") == ()
    assert install_button_label("huggingface") == "Install huggingface_hub + transformers"
    assert install_button_label("ollama") == "No library to install"


def test_pip_install_uses_this_interpreter_and_the_allowlist(monkeypatch):
    seen = {}

    def runner(command, **kwargs):
        seen["command"] = command
        seen["shell"] = kwargs.get("shell")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(pip_install.subprocess, "run", runner)
    ok, message = pip_install.install_packages(("huggingface_hub", "transformers"))
    assert ok is True
    assert seen["command"] == [sys.executable, "-m", "pip", "install", "huggingface_hub", "transformers"]
    assert seen["shell"] is False
    assert "Installed huggingface_hub and transformers" in message


def test_pip_install_refuses_an_unknown_package(monkeypatch):
    def runner(*_args, **_kwargs):
        raise AssertionError("pip must not run for an unknown package")

    monkeypatch.setattr(pip_install.subprocess, "run", runner)
    ok, message = pip_install.install_packages(("huggingface_hub", "some-random-tool"))
    assert ok is False
    assert message == "Refusing to install an unknown package."
    ok, message = pip_install.install_packages(())
    assert ok is False
    assert "separate apps" in message


def test_wizard_install_button_names_the_packages_and_runs_pip(monkeypatch):
    import time

    try:
        import ttkbootstrap as ttkb
        ttkb.Style.instance = None
        root = ttkb.Window(themename="superhero")
    except Exception:
        import tkinter as tk
        root = tk.Tk()
    root.withdraw()
    called = {}

    def fake_install(packages):
        called["packages"] = packages
        return True, "Installed huggingface_hub and transformers. Press Test in Model setup."

    monkeypatch.setattr(pip_install, "install_packages", fake_install)
    from src.presentation.model_wizard import ModelWizard

    wizard = ModelWizard(root)
    wizard.withdraw()
    try:
        wizard.update_idletasks()
        assert wizard.install_btn.cget("text") == "Install huggingface_hub + transformers"
        wizard.backend_var.set("ollama")
        wizard._on_backend()
        assert str(wizard.install_btn.cget("state")) == "disabled"
        wizard.backend_var.set("huggingface")
        wizard._on_backend()
        wizard.install_btn.invoke()
        for _ in range(100):
            wizard.update()
            if "Press Test" in wizard.result.cget("text"):
                break
            time.sleep(0.02)
        assert called["packages"] == ("huggingface_hub", "transformers")
        assert "Press Test" in wizard.result.cget("text")
        assert str(wizard.install_btn.cget("state")) == "normal"
    finally:
        wizard.destroy()
        root.destroy()
        try:
            import ttkbootstrap as ttkb
            ttkb.Style.instance = None
        except Exception:
            pass
