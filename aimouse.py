"""AI Mouse for Windows and Linux: the same hotkeys, orb and cursor-following panel as hammerspoon.lua on macOS.

    python aimouse.py            stays in the background: Win+Alt+A asks, Win+Alt+E just explains,
                                 hold Win+Alt+S and speak to ask out loud (listen.py)
    python aimouse.py --ask      one conversation, then quits (bind it to a desktop shortcut on Wayland)
    python aimouse.py --explain  the same, skipping the question

Wayland doesn't let apps see the cursor or grab global hotkeys, so there the panel opens wherever the
desktop puts it and stays there. Runs ask.py for each conversation, like Hammerspoon does.
"""
import codecs
import html
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import webview
from pynput import keyboard, mouse

DIR = os.path.dirname(os.path.abspath(__file__))
ASK = os.path.join(DIR, "ask.py")
LISTEN = os.path.join(DIR, "listen.py")
DEFAULT = "Explain what I'm pointing at."
END = "\x1e"  # ask.py prints this after each answer
WIN = sys.platform == "win32"
WAYLAND = os.environ.get("XDG_SESSION_TYPE") == "wayland"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HOTKEYS = {"<cmd>+<alt>+a": False, "<cmd>+<alt>+e": True}  # <cmd> is the Windows/Super key; value: explain

pointer = mouse.Controller()
alt = False  # held: the panel stays put, so you can move onto it to select text
held = set()  # keys down right now
listening = None  # while Win+Alt+S is held: an Event, set when it's let go
panel = orb = task = None  # the open Panel, the orb window, the running ask.py
orb_on = False


def ui(name):
    with open(os.path.join(DIR, "ui", name + ".html"), encoding="utf-8") as f:
        return f.read()


def cursor():
    """Cursor position in window coordinates, and the screen it's on."""
    x, y = pointer.position
    for s in webview.screens:
        if WIN:  # pynput reports physical pixels, windows are placed in scaled ones
            if s.physical_x <= x < s.physical_x + s.physical_width and s.physical_y <= y < s.physical_y + s.physical_height:
                return (s.x + (x - s.physical_x) / s.scale, s.y + (y - s.physical_y) / s.scale), s
        elif s.x <= x < s.x + s.width and s.y <= y < s.y + s.height:
            return (x, y), s
    return (x, y), webview.screens[0]


def beside(p, s, w, h):
    """Top-left for a w x h box beside the cursor point p, flipped to stay on screen s."""
    x, y = p[0] + 16, p[1] + 16
    if x + w > s.x + s.width:
        x = max(s.x, p[0] - 16 - w)
    if y + h > s.y + s.height:
        y = max(s.y, p[1] - 16 - h)
    return int(x), int(y)


def copy(text):
    for cmd in (["clip"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "-bi"]):
        if shutil.which(cmd[0]):  # clip.exe wants UTF-16 to keep non-English text
            subprocess.run(cmd, input=text.encode("utf-16" if cmd[0] == "clip" else "utf-8"), creationflags=NO_WINDOW)
            return


class Api:
    """What the page's post() calls. Underscored names aren't exposed to the page."""
    def __init__(self, fn):
        self._fn = fn

    def post(self, m):
        self._fn(m)


class Panel:
    """Borderless window that rides beside the cursor like the orb. Hold Alt to park it; it also stays put
    while the cursor is over it. The page posts {h} to resize; anything else goes to on_msg."""

    def __init__(self, page, w, h, on_msg, on_close=None):
        global panel
        close_panel()
        self.w, self.h, self.overflow, self.on_msg, self.on_close = w, h, False, on_msg, on_close
        self.ready, self.queued, self.lock = False, [], threading.Lock()
        p, s = cursor() if not WAYLAND else ((0, 0), None)
        self.x, self.y = beside(p, s, w, h) if s else (None, None)
        self.shown_h = h
        panel = self
        self.win = webview.create_window(
            "AI Mouse", html=ui("style") + page, js_api=Api(self.got), width=w, height=h, x=self.x, y=self.y,
            frameless=True, easy_drag=False, on_top=True, transparent=True, resizable=False, text_select=True,
            min_size=(1, 1))
        self.win.events.closed += lambda: close_panel(self)  # e.g. Alt+F4

    def got(self, m):
        if "h" in m:
            self.h, self.overflow = min(m["h"], 360), m["h"] > 360
        elif m.get("ready"):
            with self.lock:
                self.ready = True
                for code in self.queued:
                    self.win.run_js(code)
                self.queued = []
            take_focus()
        elif m.get("close"):
            close_panel(self)
        else:
            self.on_msg(m)

    def js(self, code):
        """Runs JavaScript in the page, queued until it has loaded."""
        if panel is not self:
            return  # closed or replaced
        with self.lock:
            if self.ready:
                self.win.run_js(code)
            else:
                self.queued.append(code)

    def follow(self, p, s):
        over = self.x is not None and self.x <= p[0] <= self.x + self.w and self.y <= p[1] <= self.y + self.shown_h
        if not (over or alt):
            x, y = beside(p, s, self.w, self.h)
            if (x, y) != (self.x, self.y):
                self.x, self.y = x, y
                self.win.move(x, y)
        if self.h != self.shown_h:
            self.shown_h = self.h
            self.win.resize(self.w, self.h)


def close_panel(only=None):
    global panel
    p = panel
    if not p or (only and p is not only):
        return
    panel = None
    try:
        p.win.destroy()
    except Exception:
        pass  # already gone
    if p.on_close:
        p.on_close()


def spinner(on, listening=False):
    global orb_on
    if on:
        orb.evaluate_js(f"listening = {'true' if listening else 'false'}")
    if on and not WAYLAND:
        (x, y), _ = cursor()
        orb.move(int(x + 14), int(y + 14))
    if on != orb_on:
        orb_on = on
        (orb.show if on else orb.hide)()


def take_focus():
    """Windows only lets the app you last typed in take the keyboard focus; a tap of Alt lifts that."""
    if WIN:
        import ctypes
        u = ctypes.windll.user32
        u.keybd_event(0x12, 0, 0, 0)
        u.keybd_event(0x12, 0, 2, 0)
        u.SetForegroundWindow(u.FindWindowW(None, "AI Mouse"))


def follow():
    """60 times a second: keep the orb and the panel beside the cursor."""
    while True:
        time.sleep(1 / 60)
        try:
            p, s = cursor()
            if orb_on:
                orb.move(int(p[0] + 14), int(p[1] + 14))
            if panel:
                panel.follow(p, s)
        except Exception:
            pass  # a window closed mid-move


def show_thread(thread, on_ask=None, on_close=None):
    """Conversation panel: the thread so far, plus a follow-up line when on_ask is given."""
    parts = "".join((f'<p class="q">{html.escape(t["q"])}</p>' if t.get("q") else "") + f"<p>{html.escape(t['a'])}</p>"
                    for t in thread)
    page = ui("thread").replace("{{THREAD}}", parts)
    if not on_ask:
        page = re.sub(r"<!--ask-->.*?<!--/ask-->", "", page, flags=re.S)

    def on_msg(m):
        if "copy" in m:  # nothing selected: the plain-text thread, with unrendered math
            copy(m["copy"] or "\n\n".join(x for t in thread for x in (t.get("q"), t["a"]) if x))
        elif "q" in m and on_ask:
            on_ask(m["q"])
    return Panel(page, 340, 40, on_msg, on_close)


def ai_mouse(explain, done=None, voice=False):
    """One conversation: same screenshot, follow-ups until Esc. ask.py streams each answer and ends it with END.
    With voice (an Event), the first question is spoken instead: listen.py records until the Event is set."""
    global task
    close_panel()
    if task:
        task.terminate()
    task = proc = subprocess.Popen([sys.executable, ASK] + (["--explain"] if explain else []), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    thread, cur, view, ended, ready = [], None, None, False, False

    def end():
        nonlocal ended
        ended = True
        proc.terminate()  # lets ask.py delete its screenshots
        spinner(False)
        if done:
            done()

    def ask(q):
        nonlocal cur
        cur = {"q": q, "a": ""}
        proc.stdin.write((q + "\n").encode())
        proc.stdin.flush()
        if view:
            view.js(f"addQ({json.dumps(q)})")
        elif ready:  # orb until the panel exists, but not before the screenshot, or it would be in it
            spinner(True)

    def got(text, finished):
        nonlocal view, cur
        if not view:
            spinner(False)
            view = show_thread(thread, ask, end)
            view.js(f"addQ({json.dumps(cur['q'])})")
        if text:
            cur["a"] += text
            view.js(f"addText({json.dumps(text)})")
        if finished:
            thread.append({"q": cur["q"], "a": cur["a"].strip()})
            cur = None
            view.js("finish()")

    if voice:
        rec = subprocess.Popen([sys.executable, LISTEN], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               text=True, encoding="utf-8", creationflags=NO_WINDOW)

        def let_go():
            voice.wait()
            try:
                rec.stdin.write("\n")
                rec.stdin.flush()
            except OSError:
                pass  # already quit (e.g. no ffmpeg)
        threading.Thread(target=let_go, daemon=True).start()

        def heard():
            said = rec.stdout.read().strip()
            if rec.wait() == 0 and said and proc.poll() is None:
                return ask(said)
            end()  # heard nothing, ask.py already quit, or an error (no microphone, no whisper)
            if rec.returncode and said:
                show_thread([{"a": said}])
        threading.Thread(target=heard, daemon=True).start()

    out, dec = "", codecs.getincrementaldecoder("utf-8")("replace")  # a read can end mid-character
    while chunk := proc.stdout.read1(4096):
        out += dec.decode(chunk)
        if not ready and out.startswith("ready\n"):  # screenshot taken, safe to draw on screen
            ready, out = True, out[6:]
            if explain:
                cur = {"q": DEFAULT, "a": ""}
                spinner(True)
            elif voice:
                spinner(True, listening=cur is None)  # no question yet: still listening
            else:
                sent = False

                def submitted(m):
                    nonlocal sent
                    if sent or "q" not in m:
                        return
                    sent = True
                    close_panel()
                    ask(m["q"].strip() or DEFAULT)
                Panel(ui("ask"), 300, 38, submitted, lambda: sent or end())
        while ready and cur and END in out:
            text, out = out.split(END, 1)
            out = out.removeprefix("\n")
            got(text, True)
        if ready and cur and out:
            got(out, False)
            out = ""
    if ended or task is not proc:
        return  # we closed it
    spinner(False)
    msg = "" if ready else out.strip()  # e.g. no screenshot tool
    if not msg and proc.wait() != 0:
        msg = "AI Mouse crashed:\n" + proc.stderr.read().decode("utf-8", "replace")
    if msg:
        if view:
            view.on_close = None  # replaced, not closed: don't end the app yet
        show_thread([{"a": msg}], on_close=done)
    elif done:
        done()


def on_key(k, down):
    global alt, listening
    k = key_listener.canonical(k)  # alt_l -> alt, "S" -> "s"
    if k == keyboard.Key.alt_gr:
        k = keyboard.Key.alt
    if k == keyboard.Key.alt:
        alt = down
    elif down and k == keyboard.Key.esc and panel:
        threading.Thread(target=close_panel).start()
    speak = getattr(k, "char", None) == "s" or getattr(k, "vk", None) == (0x53 if WIN else 0x73)  # S, by name or key code
    if down and speak and {keyboard.Key.cmd, keyboard.Key.alt} <= held and not listening:  # not key repeat
        listening = threading.Event()
        threading.Thread(target=ai_mouse, args=(False, None, listening)).start()
    elif not down and (speak or k in (keyboard.Key.cmd, keyboard.Key.alt)) and listening:
        listening.set()
        listening = None
    (held.add if down else held.discard)(k)

def on_scroll(x, y, dx, dy):
    # The panel rides beside the cursor, so the wheel would always hit the window underneath. While the
    # conversation overflows the panel, scroll it too. ponytail: Linux can't swallow the event, both scroll.
    p = panel
    if p and p.overflow and not WIN:
        p.js(f"b.scrollBy(0, {-dy * 40})")


def win_mouse_filter(msg, data):
    """Windows: send the wheel to the panel instead of the window under the cursor (as on macOS)."""
    p = panel
    if msg == 0x020A and p and p.overflow:  # WM_MOUSEWHEEL
        notches = ((data.mouseData >> 16) - (1 << 16 if data.mouseData >> 31 else 0)) / 120
        p.js(f"b.scrollBy(0, {-notches * 40})")
        mouse_listener.suppress_event()


def win_key_filter(msg, data):
    """Windows: Esc closes the panel and goes no further (as on macOS)."""
    if data.vkCode == 0x1B and panel:
        if msg in (0x0100, 0x0104):  # key down
            threading.Thread(target=close_panel).start()
        key_listener.suppress_event()


key_listener = keyboard.Listener(on_press=lambda k: on_key(k, True), on_release=lambda k: on_key(k, False),
                                 win32_event_filter=win_key_filter)
mouse_listener = mouse.Listener(on_scroll=on_scroll, win32_event_filter=win_mouse_filter)


def main():
    global orb
    once = "--ask" in sys.argv or "--explain" in sys.argv
    if not once and WAYLAND:
        sys.exit("Wayland doesn't allow global hotkeys. Bind desktop shortcuts to "
                 f"'{sys.executable} {__file__} --ask' and '... --explain' instead.")
    # The orb is also the always-there window pywebview needs to keep running
    orb = webview.create_window("AI Mouse orb", html=ui("orb"), width=26, height=26, hidden=True, frameless=True,
                                easy_drag=False, on_top=True, transparent=True, focus=False, resizable=False,
                                min_size=(1, 1))

    def started():
        if not WAYLAND:
            key_listener.start()
            mouse_listener.start()
            threading.Thread(target=follow, daemon=True).start()
        if once:
            ai_mouse("--explain" in sys.argv, done=orb.destroy)
        else:
            keyboard.GlobalHotKeys({k: (lambda e=e: threading.Thread(target=ai_mouse, args=(e,)).start())
                                    for k, e in HOTKEYS.items()}).start()
    webview.start(started)


if __name__ == "__main__":
    main()
