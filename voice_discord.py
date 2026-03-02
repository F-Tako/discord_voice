"""
음성 → Discord 자동 전송 앱
작은 도크 윈도우 형태

필요 라이브러리 설치:
    pip install SpeechRecognition pyaudio requests
"""

import tkinter as tk
from tkinter import simpledialog, messagebox
import threading
import queue
import time
import json
import os
import requests

try:
    import speech_recognition as sr
except ImportError:
    import sys, subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "SpeechRecognition"])
    import speech_recognition as sr

# ── 색상 ──
BG        = "#070b14"
BG2       = "#0e1420"
BG3       = "#151d2e"
BORDER    = "#1e2d47"
DISCORD   = "#5865F2"
DISCORD2  = "#4752C4"
GREEN     = "#00e5a0"
RED       = "#ff6b35"
TEXT      = "#dde6f5"
TEXT_DIM  = "#4a6080"
YELLOW    = "#fbbf24"

COLORS = ["#00c2ff","#ff6b35","#00e5a0","#ff6b9d","#c4b5fd","#fbbf24","#34d399","#f87171"]
STORAGE_FILE = os.path.join(os.path.expanduser("~"), ".voice_discord_settings.json")


def load_settings():
    try:
        with open(STORAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"webhooks": [], "last_name": ""}


def save_settings(data):
    try:
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def name_to_color(name):
    h = 0
    for c in name:
        h = (h * 31 + ord(c)) % len(COLORS)
    return COLORS[h]


class VoiceDiscordApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("음성 → Discord")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)

        # 창 크기 및 위치 (오른쪽 하단)
        w, h = 320, 500
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{sw-w-20}+{sh-h-60}")

        # 상태 변수
        self.is_listening = False
        self.auto_send    = True
        self.recognizer   = sr.Recognizer()
        self.recognizer.pause_threshold = 0.8
        self.recognizer.energy_threshold = 300
        self.mic          = None
        self.stop_event   = threading.Event()
        self.result_queue = queue.Queue()
        self.messages     = []
        self.settings     = load_settings()
        self.webhook_url  = ""
        self.user_name    = self.settings.get("last_name", "")
        self.user_color   = name_to_color(self.user_name) if self.user_name else DISCORD

        # 드래그
        self._drag_x = 0
        self._drag_y = 0

        self._build_ui()
        self._try_init_mic()
        self._poll_results()

        # 저장된 웹훅 있으면 첫 번째 자동 로드
        webhooks = self.settings.get("webhooks", [])
        if webhooks:
            self.webhook_url = webhooks[0]["url"]
            self._update_webhook_status()

        self.root.mainloop()

    # ── UI ──
    def _build_ui(self):
        # 타이틀바
        title_bar = tk.Frame(self.root, bg=DISCORD, height=36)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        title_bar.bind("<Button-1>", self._drag_start)
        title_bar.bind("<B1-Motion>", self._drag_move)

        tk.Label(title_bar, text="🎤  음성 → Discord",
                 bg=DISCORD, fg="white",
                 font=("맑은 고딕", 10, "bold")).pack(side="left", padx=10)

        tk.Button(title_bar, text="✕", bg=DISCORD, fg="white",
                  relief="flat", font=("맑은 고딕", 10, "bold"),
                  cursor="hand2", command=self.root.destroy,
                  padx=8).pack(side="right")

        # 유저 + 웹훅 설정 바
        cfg_frame = tk.Frame(self.root, bg=BG2, pady=6, padx=8)
        cfg_frame.pack(fill="x")

        # 이름
        name_row = tk.Frame(cfg_frame, bg=BG2)
        name_row.pack(fill="x", pady=(0, 4))

        self.avatar_lbl = tk.Label(name_row, text="?", bg=self.user_color,
                                   fg="white", font=("맑은 고딕", 9, "bold"),
                                   width=2, relief="flat")
        self.avatar_lbl.pack(side="left", padx=(0, 6))

        self.name_lbl = tk.Label(name_row, text=self.user_name or "이름 미설정",
                                 bg=BG2, fg=TEXT if self.user_name else TEXT_DIM,
                                 font=("맑은 고딕", 9))
        self.name_lbl.pack(side="left")

        tk.Button(name_row, text="변경", bg=BG3, fg=TEXT_DIM,
                  relief="flat", font=("맑은 고딕", 8),
                  cursor="hand2", command=self._change_name).pack(side="right")

        # 웹훅
        hook_row = tk.Frame(cfg_frame, bg=BG2)
        hook_row.pack(fill="x")

        self.hook_status = tk.Label(hook_row, text="●", fg=TEXT_DIM,
                                    bg=BG2, font=("맑은 고딕", 8))
        self.hook_status.pack(side="left", padx=(0, 4))

        self.hook_lbl = tk.Label(hook_row, text="Webhook 미설정",
                                 bg=BG2, fg=TEXT_DIM, font=("맑은 고딕", 8))
        self.hook_lbl.pack(side="left")

        hook_btns = tk.Frame(hook_row, bg=BG2)
        hook_btns.pack(side="right")

        tk.Button(hook_btns, text="입력", bg=BG3, fg=TEXT_DIM,
                  relief="flat", font=("맑은 고딕", 8),
                  cursor="hand2", command=self._input_webhook).pack(side="left", padx=(0, 2))

        tk.Button(hook_btns, text="저장목록", bg=BG3, fg=TEXT_DIM,
                  relief="flat", font=("맑은 고딕", 8),
                  cursor="hand2", command=self._show_saved_webhooks).pack(side="left")

        # 상태 바
        status_frame = tk.Frame(self.root, bg=BG3, height=24)
        status_frame.pack(fill="x")
        status_frame.pack_propagate(False)

        self.status_dot = tk.Label(status_frame, text="●", fg=TEXT_DIM,
                                   bg=BG3, font=("맑은 고딕", 7))
        self.status_dot.pack(side="left", padx=(8, 3))

        self.status_lbl = tk.Label(status_frame, text="마이크 초기화 중...",
                                   fg=TEXT_DIM, bg=BG3, font=("맑은 고딕", 8))
        self.status_lbl.pack(side="left")

        # 복사 배너
        self.banner = tk.Label(self.root, text="", bg=GREEN, fg="#003322",
                               font=("맑은 고딕", 8, "bold"), pady=3)

        # 메시지 영역
        list_frame = tk.Frame(self.root, bg=BG, padx=6, pady=4)
        list_frame.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(list_frame, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(list_frame, orient="vertical", command=self.canvas.yview,
                          bg=BG, troughcolor=BG2)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.msg_frame = tk.Frame(self.canvas, bg=BG)
        self.cw = self.canvas.create_window((0, 0), window=self.msg_frame, anchor="nw")
        self.msg_frame.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.cw, width=e.width))

        # 미리보기
        prev_frame = tk.Frame(self.root, bg=BG2, padx=8, pady=5)
        prev_frame.pack(fill="x")

        self.preview_lbl = tk.Label(prev_frame, text="음성을 인식하면 여기에 표시됩니다...",
                                    fg=TEXT_DIM, bg=BG2, font=("맑은 고딕", 8),
                                    wraplength=290, justify="left", anchor="w")
        self.preview_lbl.pack(fill="x")

        # 하단 컨트롤
        ctrl_frame = tk.Frame(self.root, bg=BG, padx=8, pady=8)
        ctrl_frame.pack(fill="x")

        self.btn_mic = tk.Button(ctrl_frame, text="🎤  시작",
                                 bg=DISCORD, fg="white",
                                 font=("맑은 고딕", 10, "bold"),
                                 relief="flat", cursor="hand2",
                                 pady=7, command=self._toggle_mic)
        self.btn_mic.pack(fill="x", pady=(0, 6))

        sub = tk.Frame(ctrl_frame, bg=BG)
        sub.pack(fill="x")

        self.btn_auto = tk.Button(sub, text="AUTO ON",
                                  bg=BG2, fg=GREEN,
                                  font=("맑은 고딕", 8),
                                  relief="flat", cursor="hand2",
                                  command=self._toggle_auto)
        self.btn_auto.pack(side="left", fill="x", expand=True, padx=(0, 2))

        tk.Button(sub, text="↩ 재전송",
                  bg=BG2, fg=TEXT_DIM,
                  font=("맑은 고딕", 8),
                  relief="flat", cursor="hand2",
                  command=self._resend_last).pack(side="left", fill="x", expand=True, padx=(2, 2))

        tk.Button(sub, text="🗑 지우기",
                  bg=BG2, fg=TEXT_DIM,
                  font=("맑은 고딕", 8),
                  relief="flat", cursor="hand2",
                  command=self._clear).pack(side="left", fill="x", expand=True, padx=(2, 0))

    # ── 이름 변경 ──
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

    # ── 웹훅 입력 ──
    def _input_webhook(self):
        url = simpledialog.askstring("Webhook URL",
                                     "Discord Webhook URL을 입력하세요:",
                                     initialvalue=self.webhook_url, parent=self.root)
        if not url:
            return

        url = url.strip()
        # JSON 자동 추출
        if url.startswith("{"):
            try:
                data = json.loads(url)
                if "url" in data:
                    url = data["url"]
            except Exception:
                pass

        if "discord.com/api/webhooks/" not in url and "discordapp.com/api/webhooks/" not in url:
            messagebox.showerror("오류", "올바른 Discord Webhook URL이 아닙니다.", parent=self.root)
            return

        self.webhook_url = url
        self._update_webhook_status()

        # 저장 여부 묻기
        save_name = simpledialog.askstring("저장",
                                           "이 웹훅을 저장할 이름을 입력하세요\n(취소하면 저장 안 함):",
                                           parent=self.root)
        if save_name and save_name.strip():
            webhooks = self.settings.get("webhooks", [])
            webhooks = [w for w in webhooks if w["url"] != url]
            webhooks.insert(0, {"name": save_name.strip(), "url": url})
            if len(webhooks) > 10:
                webhooks = webhooks[:10]
            self.settings["webhooks"] = webhooks
            save_settings(self.settings)

    # ── 저장된 웹훅 목록 ──
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

        tk.Label(win, text="저장된 Webhook 목록",
                 bg=BG, fg=TEXT, font=("맑은 고딕", 10, "bold")).pack(pady=(12, 8))

        for item in webhooks:
            row = tk.Frame(win, bg=BG2, padx=8, pady=6)
            row.pack(fill="x", padx=10, pady=2)

            tk.Label(row, text=item["name"], bg=BG2, fg=TEXT,
                     font=("맑은 고딕", 9, "bold")).pack(side="left")

            def load(u=item["url"], w=win):
                self.webhook_url = u
                self._update_webhook_status()
                self._show_banner(f"✓ 웹훅 불러옴")
                w.destroy()

            tk.Button(row, text="불러오기", bg=DISCORD, fg="white",
                      relief="flat", font=("맑은 고딕", 8),
                      cursor="hand2", command=load).pack(side="right")

    def _update_webhook_status(self):
        if self.webhook_url:
            short = self.webhook_url[-20:] if len(self.webhook_url) > 20 else self.webhook_url
            self.hook_status.config(fg=GREEN)
            self.hook_lbl.config(text=f"...{short}", fg=GREEN)
        else:
            self.hook_status.config(fg=TEXT_DIM)
            self.hook_lbl.config(text="Webhook 미설정", fg=TEXT_DIM)

    # ── 마이크 초기화 ──
    def _try_init_mic(self):
        def init():
            try:
                self.mic = sr.Microphone()
                with self.mic as src:
                    self.recognizer.adjust_for_ambient_noise(src, duration=0.5)
                self.root.after(0, lambda: self._set_status("준비됨", GREEN))
            except Exception as e:
                self.root.after(0, lambda: self._set_status(f"마이크 오류", RED))
        threading.Thread(target=init, daemon=True).start()

    def _set_status(self, text, color=TEXT_DIM):
        self.status_dot.config(fg=color)
        self.status_lbl.config(text=text, fg=color)

    # ── 마이크 토글 ──
    def _toggle_mic(self):
        if self.is_listening:
            self._stop_listening()
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
        self._set_status("인식 중...", RED)
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def _stop_listening(self):
        self.is_listening = False
        self.stop_event.set()
        self.btn_mic.config(text="🎤  시작", bg=DISCORD)
        self._set_status("준비됨", GREEN)
        self.preview_lbl.config(text="음성을 인식하면 여기에 표시됩니다...", fg=TEXT_DIM)

    # ── 음성 인식 루프 ──
    def _listen_loop(self):
        with self.mic as src:
            while not self.stop_event.is_set():
                try:
                    audio = self.recognizer.listen(src, timeout=1, phrase_time_limit=10)
                    self.root.after(0, lambda: self.preview_lbl.config(
                        text="처리 중...", fg=YELLOW))
                    text = self.recognizer.recognize_google(audio, language="ko-KR")
                    if text.strip():
                        self.result_queue.put(("final", text.strip()))
                except sr.WaitTimeoutError:
                    pass
                except sr.UnknownValueError:
                    self.root.after(0, lambda: self.preview_lbl.config(
                        text="듣고 있습니다...", fg=TEXT_DIM))
                except sr.RequestError as e:
                    self.result_queue.put(("error", f"인터넷 오류: {e}"))
                    break
                except Exception:
                    pass

    # ── 결과 폴링 ──
    def _poll_results(self):
        try:
            while True:
                kind, text = self.result_queue.get_nowait()
                if kind == "final":
                    self._add_message(text)
                elif kind == "error":
                    self._set_status(text, RED)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_results)

    # ── 메시지 추가 ──
    def _add_message(self, text):
        t = time.strftime("%H:%M")
        self.messages.append({"text": text, "time": t, "name": self.user_name})

        row = tk.Frame(self.msg_frame, bg=BG, pady=2)
        row.pack(fill="x", padx=4)

        # 헤더
        hdr = tk.Frame(row, bg=BG)
        hdr.pack(fill="x")
        tk.Label(hdr, text=self.user_name, fg=self.user_color,
                 bg=BG, font=("맑은 고딕", 8, "bold")).pack(side="left")
        tk.Label(hdr, text=f"  {t}", fg=TEXT_DIM,
                 bg=BG, font=("맑은 고딕", 7)).pack(side="left")

        # 말풍선 (클릭하면 수동 전송)
        bubble = tk.Button(row, text=text,
                           bg=BG3, fg=TEXT,
                           font=("맑은 고딕", 9),
                           relief="flat", cursor="hand2",
                           wraplength=260, justify="left",
                           padx=10, pady=6, anchor="w",
                           command=lambda t=text: self._send_discord(t, manual=True))
        bubble.pack(anchor="w", fill="x")

        self.root.after(50, lambda: self.canvas.yview_moveto(1.0))
        self.preview_lbl.config(
            text=f'✓ "{text[:28]}{"..." if len(text)>28 else ""}"', fg=GREEN)

        # 자동 전송
        if self.auto_send:
            threading.Thread(target=self._send_discord, args=(text,), daemon=True).start()

    # ── Discord 전송 ──
    def _send_discord(self, text, manual=False):
        if not self.webhook_url:
            self.root.after(0, lambda: self._show_banner("⚠️ Webhook URL을 먼저 입력하세요", RED))
            return
        content = f"[{self.user_name}] {text}"
        try:
            res = requests.post(self.webhook_url,
                                json={"content": content, "allowed_mentions": {"parse": []}},
                                timeout=5)
            if res.status_code in (200, 204):
                msg = "✓ 수동 전송 완료!" if manual else f"✅ [{self.user_name}] 전송됨"
                self.root.after(0, lambda: self._show_banner(msg))
            else:
                self.root.after(0, lambda: self._show_banner(f"⚠️ 전송 실패 ({res.status_code})", RED))
        except Exception as e:
            self.root.after(0, lambda: self._show_banner(f"⚠️ 오류: {e}", RED))

    # ── 마지막 메시지 재전송 ──
    def _resend_last(self):
        if self.messages:
            threading.Thread(target=self._send_discord,
                             args=(self.messages[-1]["text"],), kwargs={"manual": True},
                             daemon=True).start()
        else:
            self._show_banner("⚠️ 전송할 메시지 없음", RED)

    # ── AUTO 토글 ──
    def _toggle_auto(self):
        self.auto_send = not self.auto_send
        if self.auto_send:
            self.btn_auto.config(text="AUTO ON", fg=GREEN)
            self._show_banner("🤖 자동 전송 ON")
        else:
            self.btn_auto.config(text="AUTO OFF", fg=TEXT_DIM)
            self._show_banner("자동 전송 OFF — 말풍선 클릭으로 수동 전송")

    # ── 배너 ──
    def _show_banner(self, msg, color=GREEN):
        fg = "#003322" if color == GREEN else "white"
        self.banner.config(text=msg, bg=color, fg=fg)
        self.banner.pack(fill="x")
        self.root.after(2500, lambda: self.banner.pack_forget())

    # ── 지우기 ──
    def _clear(self):
        for w in self.msg_frame.winfo_children():
            w.destroy()
        self.messages.clear()
        self.preview_lbl.config(text="음성을 인식하면 여기에 표시됩니다...", fg=TEXT_DIM)

    # ── 드래그 ──
    def _drag_start(self, e):
        self._drag_x = e.x
        self._drag_y = e.y

    def _drag_move(self, e):
        x = self.root.winfo_x() + (e.x - self._drag_x)
        y = self.root.winfo_y() + (e.y - self._drag_y)
        self.root.geometry(f"+{x}+{y}")


if __name__ == "__main__":
    VoiceDiscordApp()
