"""Point the mouse at something, run this, ask a question, get an explanation.

Screenshot includes the cursor, so the model sees what you're pointing at. Hammerspoon passes
--at X,Y --screen X,Y,W,H, which adds a close-up around the cursor and captures the right display.
BACKEND "local" runs via Ollama; "claude" runs via Claude Code on your subscription.
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

BACKEND = "local"  # "local" or "claude"
MODEL = "gemma4"  # any Ollama model with "vision" in `ollama show <model>`
OLLAMA = "http://localhost:11434/api/chat"
# Shortcuts runs with a bare PATH, so fall back to the default install location
CLAUDE = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
SYSTEM = (
    "You are a helpful assistant. The first image is the user's screen. If there is a "
    "second image, it is a close-up centered exactly on the mouse cursor: the user is "
    "pointing at whatever is under the cursor at the center of that close-up, so trust it "
    "over the full screen, which is only context. Answer their question about it in plain "
    "language, briefly (under 150 words). No markdown, but write any math as LaTeX "
    "between $ signs, e.g. $N'(t) = 13$. Copy formulas exactly as written on screen; if you "
    "can't read something clearly, say so instead of guessing."
)
ZOOM_W, ZOOM_H = 480, 320  # close-up size in screen points, centered on the cursor


DEFAULT = "Explain what I'm pointing at."
END = "\x1e"  # printed after each answer so Hammerspoon knows it's complete


def show(text):
    print(text, flush=True)  # Hammerspoon shows stdout in a panel by the cursor


def read_question():
    """Next question from stdin (Hammerspoon sends it there), or None once stdin closes."""
    line = sys.stdin.readline()
    return line.strip() or DEFAULT if line else None


def ask_model(history, question, images_b64):
    messages = [{"role": "system", "content": SYSTEM}]
    for i, (q, a) in enumerate(history + [(question, None)]):
        messages.append({"role": "user", "content": q, **({"images": images_b64} if i == 0 else {})})
        if a:
            messages.append({"role": "assistant", "content": a})
    body = json.dumps({
        "model": MODEL,
        "stream": False,
        "think": False,  # ponytail: off for speed; set True for harder questions
        "messages": messages,
    }).encode()
    req = urllib.request.Request(OLLAMA, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["message"]["content"].strip()


def ask_claude(history, question, image_paths):
    # ponytail: replays the conversation as text each turn; claude -p starts fresh every time
    past = "".join(f"\nQ: {q}\nA: {a}" for q, a in history)
    prompt = "Read the screenshots at " + " and ".join(image_paths) + " (in that order)."
    if past:
        prompt += f"\nConversation so far:{past}\nNow answer the follow-up"
    r = subprocess.run(
        [CLAUDE, "-p", f"{prompt}: {question}",
         "--append-system-prompt", SYSTEM,
         "--allowedTools", "Read",
         "--strict-mcp-config",  # skip MCP servers: faster startup
         "--no-session-persistence"],
        capture_output=True, text=True, timeout=300,
        cwd=tempfile.gettempdir(),  # keep project CLAUDE.md files out of it
    )
    if r.returncode != 0:
        raise OSError(r.stderr.strip() or r.stdout.strip())
    return r.stdout.strip()


def answer(history, question, imgs):
    if BACKEND == "claude":
        try:
            return ask_claude(history, question, imgs) or "(no answer)"
        except (OSError, subprocess.TimeoutExpired) as e:
            return f"Claude Code failed: {e}"
    data = []
    for path in imgs:
        with open(path, "rb") as f:
            data.append(base64.standard_b64encode(f.read()).decode())
    try:
        return ask_model(history, question, data) or "(no answer)"
    except OSError as e:  # URLError is an OSError: Ollama not running, timeout, etc.
        return f"Couldn't reach Ollama ({e}). Is it running? Try: ollama serve"


def zoom_rect(mx, my, sx, sy, sw, sh):
    """ZOOM_W x ZOOM_H box centered on the cursor, slid inside the screen at the edges."""
    w, h = min(ZOOM_W, sw), min(ZOOM_H, sh)
    x = min(max(mx - w / 2, sx), sx + sw - w)
    y = min(max(my - h / 2, sy), sy + sh - h)
    return x, y, w, h


def main():
    tmp = tempfile.gettempdir()
    img, zoom = os.path.join(tmp, "ai_mouse.jpg"), os.path.join(tmp, "ai_mouse_zoom.jpg")
    screen, rect = [], []
    if "--at" in sys.argv and "--screen" in sys.argv:
        mx, my = map(float, sys.argv[sys.argv.index("--at") + 1].split(","))
        sx, sy, sw, sh = map(float, sys.argv[sys.argv.index("--screen") + 1].split(","))
        screen = [f"-R{sx:.0f},{sy:.0f},{sw:.0f},{sh:.0f}"]  # the display the cursor is on
        rect = zoom_rect(mx, my, sx, sy, sw, sh)
    # -C includes the cursor, -x no shutter sound; sips shrinks Retina shots so the model runs faster
    if subprocess.run(["screencapture", "-C", "-x", "-t", "jpg", *screen, img]).returncode != 0:
        subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"])
        show("No Screen Recording permission. Turn on \"Hammerspoon\" (or Terminal, if you ran "
             "this from there) in the settings window that just opened, then try again.")
        return
    subprocess.run(["sips", "-Z", "1568", img], check=True, capture_output=True)
    imgs = [img]
    if rect:
        subprocess.run(["screencapture", "-C", "-x", "-t", "jpg", "-R" + ",".join(f"{v:.0f}" for v in rect), zoom],
                       check=True)
        imgs.append(zoom)
    print("ready", flush=True)  # screenshot taken: Hammerspoon can now show the question box

    # one-press mode skips the first question; follow-ups keep coming until stdin closes
    question = DEFAULT if "--explain" in sys.argv else read_question()
    history = []
    while question is not None:
        a = answer(history, question, imgs)
        history.append((question, a))
        show(a + "\n" + END)
        question = read_question()


if __name__ == "__main__":
    assert zoom_rect(500, 400, 0, 0, 1440, 900) == (260, 240, 480, 320)  # centered
    assert zoom_rect(5, 890, 0, 0, 1440, 900) == (0, 580, 480, 320)  # slid in at a corner
    assert zoom_rect(-800, 100, -1920, 0, 1920, 1080) == (-1040, 0, 480, 320)  # screen left of main
    main()
