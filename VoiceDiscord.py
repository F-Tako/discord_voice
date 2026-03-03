"""
VoiceDiscord - 런처
- GitHub에서 최신 앱 코드 자동 다운로드
- Whisper 모델 다운로드/로딩
- 완료 후 앱 실행
"""
import tkinter as tk
from tkinter import ttk
import threading
import time
import os
import sys
import urllib.request
import importlib.util
import traceback

BG      = "#070b14"
BG2     = "#0e1420"
DISCORD = "#5865F2"
GREEN   = "#00e5a0"
RED     = "#ff6b35"
YELLOW  = "#fbbf24"
TEXT_DIM= "#4a6080"

# ── GitHub 앱 코드 URL (raw) ──
APP_CODE_URL = "https://raw.githubusercontent.com/F-Tako/discord_voice/main/app.py"
APP_CACHE    = os.path.join(os.path.expanduser("~"), ".voice_discord_app.py")

# ── Whisper 모델 ──
MODEL_URL  = "https://openaipublic.azureedge.net/main/whisper/models/9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt"
MODEL_DIR  = os.path.join(os.path.expanduser("~"), ".cache", "whisper")
MODEL_FILE = os.path.join(MODEL_DIR, "small.pt")


class Launcher:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("VoiceDiscord")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)

        w, h = 400, 240
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        self._build_ui()
        self.root.after(300, lambda: threading.Thread(target=self._run, daemon=True).start())
        self.root.mainloop()

    def _build_ui(self):
        hdr = tk.Frame(self.root, bg=DISCORD, height=46)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🎤  VoiceDiscord 시작 중...",
                 bg=DISCORD, fg="white", font=("맑은 고딕", 12, "bold")).pack(expand=True)

        self.task_lbl = tk.Label(self.root, text="준비 중...",
                                 bg=BG, fg=YELLOW, font=("맑은 고딕", 10))
        self.task_lbl.pack(pady=(18, 6))

        style = ttk.Style()
        style.theme_use("default")
        style.configure("TProgressbar", troughcolor=BG2, background=DISCORD, thickness=16)

        self.main_bar = ttk.Progressbar(self.root, length=350, mode="determinate")
        self.main_bar.pack()
        self.main_pct = tk.Label(self.root, text="0%", bg=BG, fg=TEXT_DIM, font=("맑은 고딕", 8))
        self.main_pct.pack(pady=(2, 10))

        self.sub_lbl = tk.Label(self.root, text="", bg=BG, fg=TEXT_DIM, font=("맑은 고딕", 9))
        self.sub_lbl.pack()
        self.sub_bar = ttk.Progressbar(self.root, length=350, mode="determinate")
        self.sub_bar.pack(pady=(2, 0))
        self.sub_pct = tk.Label(self.root, text="", bg=BG, fg=TEXT_DIM, font=("맑은 고딕", 8))
        self.sub_pct.pack(pady=(2, 0))

    def _ui(self, fn): self.root.after(0, fn)
    def _task(self, t, c=YELLOW): self._ui(lambda: self.task_lbl.config(text=t, fg=c))
    def _main(self, p):
        self._ui(lambda: self.main_bar.config(value=p))
        self._ui(lambda: self.main_pct.config(text=f"{int(p)}%"))
    def _sub(self, lbl, p, detail=""):
        self._ui(lambda: self.sub_lbl.config(text=lbl))
        self._ui(lambda: self.sub_bar.config(value=p))
        self._ui(lambda: self.sub_pct.config(text=detail))

    def _run(self):
        # 1. GitHub에서 최신 앱 코드 다운로드
        self._task("🔄 최신 앱 코드 확인 중...")
        self._main(5)
        try:
            urllib.request.urlretrieve(APP_CODE_URL, APP_CACHE)
            self._task("✓ 앱 코드 업데이트 완료", GREEN)
        except Exception as e:
            if os.path.exists(APP_CACHE):
                self._task(f"⚠️ 업데이트 실패, 캐시 버전 사용", YELLOW)
            else:
                self._task(f"❌ 앱 코드 다운로드 실패: {e}", RED)
                return
        self._main(15)

        # 2. Whisper 모델 다운로드
        if not os.path.exists(MODEL_FILE):
            self._task("📥 Whisper 모델 다운로드 중... (최초 1회, 약 500MB)")
            os.makedirs(MODEL_DIR, exist_ok=True)

            def progress(block, block_size, total):
                if total > 0:
                    pct    = min(block * block_size * 100 / total, 100)
                    mb     = block * block_size / 1024 / 1024
                    mb_tot = total / 1024 / 1024
                    self._sub("Whisper small 모델", pct, f"{mb:.0f} / {mb_tot:.0f} MB")
                    self._main(15 + pct * 0.65)

            try:
                urllib.request.urlretrieve(MODEL_URL, MODEL_FILE, reporthook=progress)
                self._task("✓ 모델 다운로드 완료", GREEN)
                self._sub("", 100)
            except Exception as e:
                self._task(f"❌ 모델 다운로드 실패: {e}", RED)
                return
        else:
            self._task("✓ Whisper 모델 확인됨", GREEN)
            self._main(80)

        # 3. Whisper 로딩
        self._task("⚙️ Whisper 모델 로딩 중...")
        self._sub("메모리에 로딩 중...", 0)
        self._main(82)
        try:
            import whisper as _whisper
            model = _whisper.load_model("small")
        except Exception as e:
            self._task(f"❌ 모델 로딩 실패: {e}", RED)
            return

        self._main(98)
        self._task("✅ 준비 완료! 앱 시작...", GREEN)
        self._sub("", 100)
        time.sleep(0.6)
        self._main(100)
        time.sleep(0.3)

        # 4. 앱 실행
        self.root.after(0, lambda: self._launch_app(model))

    def _launch_app(self, model):
        self.root.destroy()
        try:
            spec = importlib.util.spec_from_file_location("voice_discord_app", APP_CACHE)
            app_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(app_module)
            app_module.VoiceDiscordApp(model)
        except Exception as e:
            # 오류 표시 창
            err_root = tk.Tk()
            err_root.title("오류")
            err_root.configure(bg=BG)
            err_root.geometry("400x200")
            tk.Label(err_root, text=f"앱 실행 오류:\n{e}\n\n{traceback.format_exc()[-200:]}",
                     bg=BG, fg=RED, font=("맑은 고딕", 8),
                     wraplength=380, justify="left").pack(padx=10, pady=10)
            err_root.mainloop()


if __name__ == "__main__":
    Launcher()
