"""
VoiceDiscord 앱 코드
GitHub에서 자동으로 최신 버전을 받아옵니다.
이 파일만 수정하면 exe 재빌드 없이 자동 반영됩니다!
"""
import tkinter as tk
from tkinter import simpledialog
from tkinter import messagebox
import threading
import queue
import time
import json
import os
import wave
import tempfile
import struct
import math
import pyaudio
import requests

BG       = "#070b14"
BG2      = "#0e1420"
BG3      = "#151d2e"
DISCORD  = "#5865F2"
GREEN    = "#00e5a0"
RED      = "#ff6b35"
TEXT     = "#dde6f5"
TEXT_DIM = "#4a6080"
YELLOW   = "#fbbf24"
COLORS   = ["#00c2ff","#ff6b35","#00e5a0","#ff6b9d","#c4b5fd","#fbbf24","#34d399","#f87171"]

STORAGE_FILE = os.path.join(os.path.expanduser("~"), ".voice_discord_settings.json")
RATE           = 16000
CHUNK          = 1024
SILENCE_THRESH = 300
SILENCE_SEC    = 1.2


def rms(data):
    count = len(data) // 2
    if count == 0: return 0
    shorts = struct.unpack("%dh" % count, data)
    return math.sqrt(sum(s * s for s in shorts) / count)


def load_settings():
    try:
        with open(STORAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"webhooks": [], "last_name": ""}


def save_settings(data):
    try:
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass


def name_to_color(name):
    h = 0
    for c in name: h = (h * 31 + ord(c)) % len(COLORS)
    return COLORS[h]


class VoiceDiscordApp:
    def __init__(self, model):
        self.model = model
        self.root = tk.Tk()
        self.root.title("음성 → Discord")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)

        w, h = 320, 520
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{sw-w-20}+{sh-h-60}")

        self.is_listening = False
        self.auto_send    = True
        self.stop_event   = threading.Event()
        self.result_queue = queue.Queue()
        self.messages     = []
        self.settings     = load_settings()
        self.webhook_url  = ""
        self.user_name    = self.settings.get("last_name", "")
        self.user_color   = name_to_color(self.user_name) if self.user_name else DISCORD
        self._drag_x = 0
        self._drag_y = 0

        self._build_ui()
        self._poll_results()

        webhooks = self.settings.get("webhooks", [])
        if webhooks:
            self.webhook_url = webhooks[0]["url"]
            self._update_webhook_status()

        self.root.mainloop()

    def _build_ui(self):
        title_bar = tk.Frame(self.root, bg=DISCORD, height=36)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        title_bar.bind("<Button-1>", self._drag_start)
        title_bar.bind("<B1-Motion>", self._drag_move)
        tk.Label(title_bar, text="🎤  음성 → Discord",
                 bg=DISCORD, fg="white", font=("맑은 고딕", 10, "bold")).pack(side="left", padx=10)
        tk.Button(title_bar, text="✕", bg=DISCORD, fg="white", relief="flat",
                  font=("맑은 고딕", 10), cursor="hand2",
                  command=self.root.destroy, padx=8).pack(side="right")

        cfg = tk.Frame(self.root, bg=BG2, pady=6, padx=8)
        cfg.pack(fill="x")
        name_row = tk.Frame(cfg, bg=BG2)
        name_row.pack(fill="x", pady=(0, 4))
        self.avatar_lbl = tk.Label(name_row,
                                   text=self.user_name[0] if self.user_name else "?",
                                   bg=self.user_color, fg="white",
                                   font=("맑은 고딕", 9, "bold"), width=2)
        self.avatar_lbl.pack(side="left", padx=(0, 6))
        self.name_lbl = tk.Label(name_row, text=self.user_name or "이름 미설정",
                                 bg=BG2, fg=TEXT if self.user_name else TEXT_DIM,
                                 font=("맑은 고딕", 9))
        self.name_lbl.pack(side="left")
        tk.Button(name_row, text="변경", bg=BG3, fg=TEXT_DIM, relief="flat",
                  font=("맑은 고딕", 8), cursor="hand2",
                  command=self._change_name).pack(side="right")

        hook_row = tk.Frame(cfg, bg=BG2)
        hook_row.pack(fill="x")
        self.hook_status = tk.Label(hook_row, text="●", fg=TEXT_DIM, bg=BG2, font=("맑은 고딕", 8))
        self.hook_status.pack(side="left", padx=(0, 4))
        self.hook_lbl = tk.Label(hook_row, text="Webhook 미설정",
                                 bg=BG2, fg=TEXT_DIM, font=("맑은 고딕", 8))
        self.hook_lbl.pack(side="left")
        hb = tk.Frame(hook_row, bg=BG2)
        hb.pack(side="right")
        tk.Button(hb, text="입력", bg=BG3, fg=TEXT_DIM, relief="flat",
                  font=("맑은 고딕", 8), cursor="hand2",
                  command=self._input_webhook).pack(side="left", padx=(0, 2))
        tk.Button(hb, text="저장목록", bg=BG3, fg=TEXT_DIM, relief="flat",
                  font=("맑은 고딕", 8), cursor="hand2",
                  command=self._show_saved_webhooks).pack(side="left")

        sf_bar = tk.Frame(self.root, bg=BG3, height=24)
        sf_bar.pack(fill="x")
        sf_bar.pack_propagate(False)
        self.status_dot = tk.Label(sf_bar, text="●", fg=GREEN, bg=BG3, font=("맑은 고딕", 7))
        self.status_dot.pack(side="left", padx=(8, 3))
        self.status_lbl = tk.Label(sf_bar, text="준비됨 ✓", fg=GREEN, bg=BG3, font=("맑은 고딕", 8))
        self.status_lbl.pack(side="left")

        self.banner = tk.Label(self.root, text="", bg=GREEN, fg="#003322",
                               font=("맑은 고딕", 8, "bold"), pady=3)

        lf = tk.Frame(self.root, bg=BG, padx=6, pady=4)
        lf.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(lf, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(lf, orient="vertical", command=self.canvas.yview,
                          bg=BG, troughcolor=BG2)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.msg_frame = tk.Frame(self.canvas, bg=BG)
        self.cw = self.canvas.create_window((0, 0), window=self.msg_frame, anchor="nw")
        self.msg_frame.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.cw, width=e.width))

        pf = tk.Frame(self.root, bg=BG2, padx=8, pady=5)
        pf.pack(fill="x")
        self.preview_lbl = tk.Label(pf, text="음성을 인식하면 여기에 표시됩니다...",
                                    fg=TEXT_DIM, bg=BG2, font=("맑은 고딕", 8),
                                    wraplength=290, justify="left", anchor="w")
        self.preview_lbl.pack(fill="x")

        ctrl = tk.Frame(self.root, bg=BG, padx=8, pady=8)
        ctrl.pack(fill="x")
        self.btn_mic = tk.Button(ctrl, text="🎤  시작", bg=DISCORD, fg="white",
                                 font=("맑은 고딕", 10, "bold"), relief="flat",
                                 cursor="hand2", pady=7, command=self._toggle_mic)
        self.btn_mic.pack(fill="x", pady=(0, 6))
        sub = tk.Frame(ctrl, bg=BG)
        sub.pack(fill="x")
        self.btn_auto = tk.Button(sub, text="AUTO ON", bg=BG2, fg=GREEN,
                                  font=("맑은 고딕", 8), relief="flat",
                                  cursor="hand2", command=self._toggle_auto)
        self.btn_auto.pack(side="left", fill="x", expand=True, padx=(0, 2))
        tk.Button(sub, text="↩ 재전송", bg=BG2, fg=TEXT_DIM, font=("맑은 고딕", 8),
                  relief="flat", cursor="hand2",
                  command=self._resend_last).pack(side="left", fill="x", expand=True, padx=(2, 2))
        tk.Button(sub, text="🗑 지우기", bg=BG2, fg=TEXT_DIM, font=("맑은 고딕", 8),
                  relief="flat", cursor="hand2",
                  command=self._clear).pack(side="left", fill="x", expand=True, padx=(2, 0))

    def _set_status(self, text, color=TEXT_DIM):
        self.status_dot.config(fg=color)
        self.status_lbl.config(text=text, fg=color)

    def _change_name(self):
        name = simpledialog.askstring("이름 설정", "사용할 이름을 입력하세요:",
                                      initialvalue=self.user_name, parent=self.root)
        if name and name.strip():
            self.user_name = name.strip()
            self.user_color = name_to_color(self.user_name)
            self.name_lbl.config(text=self.user_name, fg=TEXT)
            self.avatar_lbl.config(text=self.user_name[0], bg=self.user_color)
            self.settings["last_name"] = self.user_name
            save_settings(self.settings)

    def _input_webhook(self):
        url = simpledialog.askstring("Webhook URL", "Discord Webhook URL을 입력하세요:",
                                     initialvalue=self.webhook_url, parent=self.root)
        if not url: return
        url = url.strip()
        if url.startswith("{"):
            try:
                data = json.loads(url)
                if "url" in data: url = data["url"]
            except: pass
        if "discord.com/api/webhooks/" not in url:
            messagebox.showerror("오류", "올바른 Discord Webhook URL이 아닙니다.", parent=self.root)
            return
        self.webhook_url = url
        self._update_webhook_status()
        save_name = simpledialog.askstring("저장", "웹훅 저장 이름 (취소하면 저장 안 함):",
                                           parent=self.root)
        if save_name and save_name.strip():
            webhooks = self.settings.get("webhooks", [])
            webhooks = [w for w in webhooks if w["url"] != url]
            webhooks.insert(0, {"name": save_name.strip(), "url": url})
            self.settings["webhooks"] = webhooks[:10]
            save_settings(self.settings)

    def _show_saved_webhooks(self):
        webhooks = self.settings.get("webhooks", [])
        if not webhooks:
            messagebox.showinfo("저장된 웹훅", "저장된 웹훅이 없습니다.", parent=self.root)
            return
        win = tk.Toplevel(self.root)
        win.title("저장된 Webhook")
        win.configure(bg=BG)
        win.geometry("280x300")
        win.attributes("-topmost", True)
        tk.Label(win, text="저장된 Webhook 목록", bg=BG, fg=TEXT,
                 font=("맑은 고딕", 10, "bold")).pack(pady=(12, 8))
        for item in webhooks:
            row = tk.Frame(win, bg=BG2, padx=8, pady=6)
            row.pack(fill="x", padx=10, pady=2)
            tk.Label(row, text=item["name"], bg=BG2, fg=TEXT,
                     font=("맑은 고딕", 9, "bold")).pack(side="left")
            def load_hook(u=item["url"], w=win):
                self.webhook_url = u
                self._update_webhook_status()
                self._show_banner("✓ 웹훅 불러옴")
                w.destroy()
            tk.Button(row, text="불러오기", bg=DISCORD, fg="white", relief="flat",
                      font=("맑은 고딕", 8), cursor="hand2", command=load_hook).pack(side="right")

    def _update_webhook_status(self):
        if self.webhook_url:
            self.hook_status.config(fg=GREEN)
            self.hook_lbl.config(text=f"...{self.webhook_url[-20:]}", fg=GREEN)
        else:
            self.hook_status.config(fg=TEXT_DIM)
            self.hook_lbl.config(text="Webhook 미설정", fg=TEXT_DIM)

    def _toggle_mic(self):
        if self.is_listening: self._stop_listening()
        else:
            if not self.user_name:
                messagebox.showwarning("이름 미설정", "먼저 이름을 설정해주세요!", parent=self.root)
                return
            if not self.webhook_url:
                messagebox.showwarning("웹훅 미설정", "먼저 Webhook URL을 입력해주세요!", parent=self.root)
                return
            self._start_listening()

    def _start_listening(self):
        self.is_listening = True
        self.stop_event.clear()
        self.btn_mic.config(text="⏹  중지", bg=RED)
        self._set_status("듣는 중... (말하고 잠깐 멈추면 인식)", RED)
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def _stop_listening(self):
        self.is_listening = False
        self.stop_event.set()
        self.btn_mic.config(text="🎤  시작", bg=DISCORD)
        self._set_status("준비됨 ✓", GREEN)
        self.preview_lbl.config(text="음성을 인식하면 여기에 표시됩니다...", fg=TEXT_DIM)

    def _listen_loop(self):
        pa = pyaudio.PyAudio()
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE,
                         input=True, frames_per_buffer=CHUNK)
        frames = []
        silent_chunks = 0
        speaking = False
        silence_limit = int(SILENCE_SEC * RATE / CHUNK)
        try:
            while not self.stop_event.is_set():
                data = stream.read(CHUNK, exception_on_overflow=False)
                vol = rms(data)
                if vol > SILENCE_THRESH:
                    speaking = True
                    silent_chunks = 0
                    frames.append(data)
                    self.root.after(0, lambda: self.preview_lbl.config(
                        text="🎤 말하는 중...", fg=RED))
                elif speaking:
                    frames.append(data)
                    silent_chunks += 1
                    if silent_chunks >= silence_limit:
                        audio_data = b"".join(frames)
                        self.root.after(0, lambda: self.preview_lbl.config(
                            text="⏳ 인식 중...", fg=YELLOW))
                        threading.Thread(target=self._transcribe,
                                         args=(audio_data,), daemon=True).start()
                        frames = []
                        silent_chunks = 0
                        speaking = False
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

    def _transcribe(self, audio_data):
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(RATE)
                wf.writeframes(audio_data)
            result = self.model.transcribe(tmp_path, language="ko", fp16=False, temperature=0)
            text = result["text"].strip()
            os.unlink(tmp_path)
            if text:
                self.result_queue.put(("final", text))
        except Exception as e:
            self.result_queue.put(("error", str(e)))

    def _poll_results(self):
        try:
            while True:
                kind, text = self.result_queue.get_nowait()
                if kind == "final": self._add_message(text)
                elif kind == "error": self._set_status(f"오류: {text}", RED)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_results)

    def _add_message(self, text):
        t = time.strftime("%H:%M")
        self.messages.append({"text": text, "time": t})
        row = tk.Frame(self.msg_frame, bg=BG, pady=2)
        row.pack(fill="x", padx=4)
        hdr = tk.Frame(row, bg=BG)
        hdr.pack(fill="x")
        tk.Label(hdr, text=self.user_name, fg=self.user_color,
                 bg=BG, font=("맑은 고딕", 8, "bold")).pack(side="left")
        tk.Label(hdr, text=f"  {t}", fg=TEXT_DIM, bg=BG, font=("맑은 고딕", 7)).pack(side="left")
        bubble = tk.Button(row, text=text, bg=BG3, fg=TEXT, font=("맑은 고딕", 9),
                           relief="flat", cursor="hand2", wraplength=260,
                           justify="left", padx=10, pady=6, anchor="w",
                           command=lambda t=text: self._send_discord(t, manual=True))
        bubble.pack(anchor="w", fill="x")
        self.root.after(50, lambda: self.canvas.yview_moveto(1.0))
        self.preview_lbl.config(
            text=f'✓ "{text[:28]}{"..." if len(text) > 28 else ""}"', fg=GREEN)
        if self.auto_send:
            threading.Thread(target=self._send_discord, args=(text,), daemon=True).start()

    def _send_discord(self, text, manual=False):
        if not self.webhook_url:
            self.root.after(0, lambda: self._show_banner("⚠️ Webhook URL을 먼저 입력하세요", RED))
            return
        try:
            res = requests.post(self.webhook_url,
                                json={"content": f"[{self.user_name}] {text}",
                                      "allowed_mentions": {"parse": []}}, timeout=5)
            if res.status_code in (200, 204):
                self.root.after(0, lambda: self._show_banner(
                    "✓ 수동 전송!" if manual else "✅ 전송됨"))
            else:
                self.root.after(0, lambda: self._show_banner(
                    f"⚠️ 전송 실패 ({res.status_code})", RED))
        except Exception as e:
            self.root.after(0, lambda: self._show_banner(f"⚠️ 오류: {e}", RED))

    def _resend_last(self):
        if self.messages:
            threading.Thread(target=self._send_discord,
                             args=(self.messages[-1]["text"],),
                             kwargs={"manual": True}, daemon=True).start()
        else:
            self._show_banner("⚠️ 전송할 메시지 없음", RED)

    def _toggle_auto(self):
        self.auto_send = not self.auto_send
        self.btn_auto.config(text="AUTO ON" if self.auto_send else "AUTO OFF",
                             fg=GREEN if self.auto_send else TEXT_DIM)
        self._show_banner("🤖 자동 전송 ON" if self.auto_send else "자동 전송 OFF")

    def _show_banner(self, msg, color=GREEN):
        self.banner.config(text=msg, bg=color, fg="#003322" if color == GREEN else "white")
        self.banner.pack(fill="x")
        self.root.after(2500, lambda: self.banner.pack_forget())

    def _clear(self):
        for w in self.msg_frame.winfo_children(): w.destroy()
        self.messages.clear()
        self.preview_lbl.config(text="음성을 인식하면 여기에 표시됩니다...", fg=TEXT_DIM)

    def _drag_start(self, e): self._drag_x = e.x; self._drag_y = e.y
    def _drag_move(self, e):
        self.root.geometry(
            f"+{self.root.winfo_x()+(e.x-self._drag_x)}+{self.root.winfo_y()+(e.y-self._drag_y)}")
