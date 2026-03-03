"""
VoiceDiscord 앱 코드
GitHub에서 자동으로 최신 버전을 받아옵니다.
"""
import tkinter as tk
import threading
import queue
import time
import json
import os
import wave
import tempfile
import struct
import math
import ctypes
import ctypes.wintypes

import requests

# ── Windows WinMM 마이크 녹음 ──
winmm = ctypes.windll.winmm

WAVE_FORMAT_PCM = 0x0001
RATE  = 16000
CHANNELS = 1
BITS  = 16
CHUNK_MS = 100  # 100ms 단위로 읽기

class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag",      ctypes.wintypes.WORD),
        ("nChannels",       ctypes.wintypes.WORD),
        ("nSamplesPerSec",  ctypes.wintypes.DWORD),
        ("nAvgBytesPerSec", ctypes.wintypes.DWORD),
        ("nBlockAlign",     ctypes.wintypes.WORD),
        ("wBitsPerSample",  ctypes.wintypes.WORD),
        ("cbSize",          ctypes.wintypes.WORD),
    ]

class WAVEHDR(ctypes.Structure):
    _fields_ = [
        ("lpData",          ctypes.c_char_p),
        ("dwBufferLength",  ctypes.wintypes.DWORD),
        ("dwBytesRecorded", ctypes.wintypes.DWORD),
        ("dwUser",          ctypes.wintypes.DWORD),
        ("dwFlags",         ctypes.wintypes.DWORD),
        ("dwLoops",         ctypes.wintypes.DWORD),
        ("lpNext",          ctypes.c_void_p),
        ("reserved",        ctypes.wintypes.DWORD),
    ]

WHDR_DONE = 0x00000001

def record_chunk(hwi, buf_size):
    buf = ctypes.create_string_buffer(buf_size)
    hdr = WAVEHDR()
    hdr.lpData = ctypes.cast(buf, ctypes.c_char_p)
    hdr.dwBufferLength = buf_size
    hdr.dwFlags = 0
    winmm.waveInPrepareHeader(hwi, ctypes.byref(hdr), ctypes.sizeof(hdr))
    winmm.waveInAddBuffer(hwi, ctypes.byref(hdr), ctypes.sizeof(hdr))
    winmm.waveInStart(hwi)
    # 버퍼가 채워질 때까지 대기
    timeout = time.time() + 1.0
    while not (hdr.dwFlags & WHDR_DONE):
        time.sleep(0.005)
        if time.time() > timeout:
            break
    winmm.waveInStop(hwi)
    winmm.waveInUnprepareHeader(hwi, ctypes.byref(hdr), ctypes.sizeof(hdr))
    return buf.raw[:hdr.dwBytesRecorded]

def open_mic():
    fmt = WAVEFORMATEX()
    fmt.wFormatTag      = WAVE_FORMAT_PCM
    fmt.nChannels       = CHANNELS
    fmt.nSamplesPerSec  = RATE
    fmt.wBitsPerSample  = BITS
    fmt.nBlockAlign     = CHANNELS * BITS // 8
    fmt.nAvgBytesPerSec = RATE * fmt.nBlockAlign
    fmt.cbSize          = 0
    hwi = ctypes.wintypes.HANDLE()
    ret = winmm.waveInOpen(ctypes.byref(hwi), 0xFFFFFFFF,
                           ctypes.byref(fmt), 0, 0, 0)
    if ret != 0:
        raise RuntimeError(f"waveInOpen 실패: {ret}")
    return hwi

def close_mic(hwi):
    winmm.waveInReset(hwi)
    winmm.waveInClose(hwi)

# ── 색상 ──
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

STORAGE_FILE   = os.path.join(os.path.expanduser("~"), ".voice_discord_settings.json")
SILENCE_THRESH = 300
SILENCE_SEC    = 1.2
BUF_SIZE       = int(RATE * (BITS // 8) * CHANNELS * CHUNK_MS / 1000)


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

# ── 커스텀 다이얼로그 ──
def _ask_string(title, prompt, initialvalue="", parent=None):
    result = [None]
    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(bg=BG)
    win.resizable(False, False)
    win.attributes("-topmost", True)
    win.geometry("320x130")
    win.transient(parent)
    win.grab_set()
    tk.Label(win, text=prompt, bg=BG, fg=TEXT, font=("맑은 고딕", 9)).pack(pady=(14, 4))
    entry = tk.Entry(win, font=("맑은 고딕", 9), width=36)
    entry.insert(0, initialvalue)
    entry.pack(pady=4)
    entry.focus()
    def ok(e=None):
        result[0] = entry.get()
        win.destroy()
    def cancel(e=None):
        win.destroy()
    bf = tk.Frame(win, bg=BG)
    bf.pack(pady=6)
    tk.Button(bf, text="확인", bg=DISCORD, fg="white", relief="flat",
              font=("맑은 고딕", 9), cursor="hand2", padx=12, command=ok).pack(side="left", padx=4)
    tk.Button(bf, text="취소", bg=BG3, fg=TEXT_DIM, relief="flat",
              font=("맑은 고딕", 9), cursor="hand2", padx=12, command=cancel).pack(side="left", padx=4)
    entry.bind("<Return>", ok)
    entry.bind("<Escape>", cancel)
    win.wait_window()
    return result[0]

def _show_popup(title, msg, color=TEXT, parent=None):
    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(bg=BG)
    win.resizable(False, False)
    win.attributes("-topmost", True)
    win.geometry("300x120")
    win.transient(parent)
    win.grab_set()
    tk.Label(win, text=msg, bg=BG, fg=color,
             font=("맑은 고딕", 9), wraplength=280).pack(pady=(18, 8))
    tk.Button(win, text="확인", bg=DISCORD, fg="white", relief="flat",
              font=("맑은 고딕", 9), cursor="hand2", padx=12,
              command=win.destroy).pack()
    win.wait_window()


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
        name = _ask_string("이름 설정", "사용할 이름을 입력하세요:",
                           initialvalue=self.user_name, parent=self.root)
        if name and name.strip():
            self.user_name = name.strip()
            self.user_color = name_to_color(self.user_name)
            self.name_lbl.config(text=self.user_name, fg=TEXT)
            self.avatar_lbl.config(text=self.user_name[0], bg=self.user_color)
            self.settings["last_name"] = self.user_name
            save_settings(self.settings)

    def _input_webhook(self):
        url = _ask_string("Webhook URL", "Discord Webhook URL을 입력하세요:",
                          initialvalue=self.webhook_url, parent=self.root)
        if not url: return
        url = url.strip()
        if url.startswith("{"):
            try:
                data = json.loads(url)
                if "url" in data: url = data["url"]
            except: pass
        if "discord.com/api/webhooks/" not in url:
            _show_popup("오류", "올바른 Discord Webhook URL이 아닙니다.", RED, parent=self.root)
            return
        self.webhook_url = url
        self._update_webhook_status()
        save_name = _ask_string("저장", "웹훅 저장 이름 (취소하면 저장 안 함):", parent=self.root)
        if save_name and save_name.strip():
            webhooks = self.settings.get("webhooks", [])
            webhooks = [w for w in webhooks if w["url"] != url]
            webhooks.insert(0, {"name": save_name.strip(), "url": url})
            self.settings["webhooks"] = webhooks[:10]
            save_settings(self.settings)

    def _show_saved_webhooks(self):
        webhooks = self.settings.get("webhooks", [])
        if not webhooks:
            _show_popup("저장된 웹훅", "저장된 웹훅이 없습니다.", TEXT, parent=self.root)
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
                _show_popup("이름 미설정", "먼저 이름을 설정해주세요!", YELLOW, parent=self.root)
                return
            if not self.webhook_url:
                _show_popup("웹훅 미설정", "먼저 Webhook URL을 입력해주세요!", YELLOW, parent=self.root)
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
        try:
            hwi = open_mic()
        except Exception as e:
            self.root.after(0, lambda: self._set_status(f"마이크 오류: {e}", RED))
            self.is_listening = False
            self.root.after(0, lambda: self.btn_mic.config(text="🎤  시작", bg=DISCORD))
            return

        frames = []
        silent_chunks = 0
        speaking = False
        silence_limit = int(SILENCE_SEC * 1000 / CHUNK_MS)

        try:
            while not self.stop_event.is_set():
                data = record_chunk(hwi, BUF_SIZE)
                if not data:
                    continue
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
            close_mic(hwi)

    def _transcribe(self, audio_data):
        try:
            import numpy as np
            # wav 파일 없이 numpy 배열로 직접 Whisper에 넘김 (ffmpeg 불필요)
            audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            result = self.model.transcribe(audio_np, language="ko", fp16=False, temperature=0)
            text = result["text"].strip()
            if text:
                self.result_queue.put(("final", text))
        except Exception as e:
            self.result_queue.put(("error", f"[인식 오류] {e}"))

    def _poll_results(self):
        try:
            while True:
                kind, text = self.result_queue.get_nowait()
                if kind == "final": self._add_message(text)
                elif kind == "error":
                    self._set_status(f"오류: {text}", RED)
                    self._add_error_message(text)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_results)

    def _add_error_message(self, text):
        row = tk.Frame(self.msg_frame, bg=BG, pady=2)
        row.pack(fill="x", padx=4)
        tk.Label(row, text=f"⚠️ {text}", bg=BG, fg=RED,
                 font=("맑은 고딕", 8), wraplength=280, justify="left", anchor="w").pack(fill="x", padx=4)
        self.root.after(50, lambda: self.canvas.yview_moveto(1.0))

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
