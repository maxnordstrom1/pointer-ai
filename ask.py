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
    "can't read something clearly, say so instead of guessing. Always reply in the language "
    "of the user's latest question. If that question is exactly \"Explain what I'm pointing "
    "at.\" (sent when they typed nothing), reply in the language of the text on screen "
    "around the cursor instead."
)
ZOOM_W, ZOOM_H = 480, 320  # close-up size in screen points, centered on the cursor


DEFAULT = "Explain what I'm pointing at."
END = "\x1e"  # printed after each answer so Hammerspoon knows it's complete


def show(text):
    print(text, flush=True)  # Hammerspoon shows stdout in a panel by the cursor


# Help for small models, done by macOS on device: NaturalLanguage spots the language of a question,
# Vision reads the text in the close-up (to find the line under the cursor, and the screen's language).
VISION_JS = r"""
ObjC.import("NaturalLanguage"); ObjC.import("Vision")
// argv: "lang" <text>  -> language in English ("Swedish"), or nothing if unsure
//       "ocr" <path>   -> JSON [[text, x, y, w, h], ...], boxes 0-1 with the origin at the bottom left
function run(argv) {
  if (argv[0] === "ocr") {
    const req = $.VNRecognizeTextRequest.alloc.init
    req.automaticallyDetectsLanguage = true
    $.VNImageRequestHandler.alloc.initWithURLOptions($.NSURL.fileURLWithPath(argv[1]), $()).performRequestsError($([req]), null)
    const out = [], res = req.results
    for (let i = 0; i < res.count; i++) {
      const o = res.objectAtIndex(i), b = o.boundingBox
      out.push([o.topCandidates(1).firstObject.string.js, b.origin.x, b.origin.y, b.size.width, b.size.height])
    }
    return JSON.stringify(out)
  }
  const r = $.NLLanguageRecognizer.alloc.init
  r.processString(argv[1])
  const hyp = r.languageHypothesesWithMaximum(1)
  const code = hyp.allKeys.firstObject
  if (!code.js || hyp.objectForKey(code).js < 0.8) return ""
  return $.NSLocale.localeWithLocaleIdentifier("en").localizedStringForLanguageCode(code).js
}
"""


def vision(*args, wait=True):
    p = subprocess.Popen(["osascript", "-l", "JavaScript", "-e", VISION_JS, *args],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return p.communicate()[0].strip() if wait else p


def language(text):
    """English name of the language ("Swedish"), or "" if macOS isn't confident."""
    return vision("lang", text)


def line_at(lines, cx, cy):
    """Text of the OCR line nearest the point (0-1, origin top left), or "" if none is close."""
    best, best_d = "", 0.08  # ponytail: nearest single line; widen if the anchor misses multi-line items
    for text, x, y, w, h in lines:
        y = 1 - y - h  # Vision's origin is bottom left
        d = max(x - cx, 0, cx - x - w) + max(y - cy, 0, cy - y - h)
        if d < best_d:
            best, best_d = text, d
    return best


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
        "stream": True,
        "think": False,  # ponytail: off for speed; set True for harder questions
        "messages": messages,
    }).encode()
    req = urllib.request.Request(OLLAMA, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        for line in r:  # one JSON object per line as the answer is generated
            yield json.loads(line)["message"].get("content", "")  # thinking arrives separately, skipped


def ask_claude(history, question, image_paths):
    # ponytail: replays the conversation as text each turn; claude -p starts fresh every time
    past = "".join(f"\nQ: {q}\nA: {a}" for q, a in history)
    prompt = "Read the screenshots at " + " and ".join(image_paths) + " (in that order)."
    if past:
        prompt += f"\nConversation so far:{past}\nNow answer the follow-up"
    p = subprocess.Popen(
        [CLAUDE, "-p", f"{prompt}: {question}",
         "--append-system-prompt", SYSTEM,
         "--allowedTools", "Read",
         "--output-format", "stream-json", "--verbose", "--include-partial-messages",  # stream the text
         "--strict-mcp-config",  # skip MCP servers: faster startup
         "--no-session-persistence"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=tempfile.gettempdir(),  # keep project CLAUDE.md files out of it
    )
    streamed = False
    for line in p.stdout:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        e = d.get("event", {})
        if d.get("type") == "stream_event" and e.get("type") == "content_block_delta" \
                and e["delta"].get("type") == "text_delta":
            streamed = True
            yield e["delta"]["text"]
        elif d.get("type") == "result" and not streamed:  # nothing streamed: use the final text
            yield d.get("result") or ""
    if p.wait() != 0 and not streamed:
        raise OSError(p.stderr.read().strip())


def answer(history, question, imgs):
    """Yields the answer in pieces as the model writes it."""
    if BACKEND == "claude":
        try:
            yield from ask_claude(history, question, imgs)
        except OSError as e:
            yield f"Claude Code failed: {e}"
        return
    data = []
    for path in imgs:
        with open(path, "rb") as f:
            data.append(base64.standard_b64encode(f.read()).decode())
    try:
        yield from ask_model(history, question, data)
    except OSError as e:  # URLError is an OSError: Ollama not running, timeout, etc.
        yield f"Couldn't reach Ollama ({e}). Is it running? Try: ollama serve"


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
    ocr = vision("ocr", imgs[-1], wait=False)  # runs while the user types the question
    print("ready", flush=True)  # screenshot taken: Hammerspoon can now show the question box

    # one-press mode skips the first question; follow-ups keep coming until stdin closes
    question = DEFAULT if "--explain" in sys.argv else read_question()
    try:
        lines = json.loads(ocr.communicate()[0])
    except ValueError:
        lines = []
    anchor = ""
    if rect:  # where the cursor sits in the close-up (it's off centre when slid in at a screen edge)
        # +3pt: the hotspot is the arrow's tip, but people aim with the arrow's body just below it
        anchor = line_at(lines, (mx - rect[0]) / rect[2], (my + 3 - rect[1]) / rect[3])
    history, lang = [], ""
    while question is not None:
        if question == DEFAULT:  # nothing typed: the language of the text by the cursor
            lang = language(" ".join(t[0] for t in lines)) or lang
        else:
            lang = language(question) or lang  # "ok", "why?": keep the previous language
        notes = []
        if anchor and not history:  # small models drift to whatever stands out, so name the spot
            notes.append(f"The text under the cursor reads roughly: \"{anchor}\" (machine-read, so "
                         "symbols may be garbled: take exact math from the image). Answer about that.")
        if lang:
            notes.append(f"Reply in {lang}.")
        if notes:
            question += "\n\n(" + " ".join(notes) + ")"
        parts = []
        for piece in answer(history, question, imgs):
            print(piece, end="", flush=True)  # Hammerspoon types it out as it arrives
            parts.append(piece)
        a = "".join(parts).strip()
        if not a:
            a = "(no answer)"
            print(a, end="")
        history.append((question, a))
        show("\n" + END)
        question = read_question()


if __name__ == "__main__":
    assert zoom_rect(500, 400, 0, 0, 1440, 900) == (260, 240, 480, 320)  # centered
    assert zoom_rect(5, 890, 0, 0, 1440, 900) == (0, 580, 480, 320)  # slid in at a corner
    assert zoom_rect(-800, 100, -1920, 0, 1920, 1080) == (-1040, 0, 480, 320)  # screen left of main
    box = [["far", 0.0, 0.9, 0.1, 0.05], ["b) here", 0.41, 0.45, 0.13, 0.04]]  # Vision boxes, origin bottom left
    assert line_at(box, 0.5, 0.5) == "b) here" and line_at(box, 0.9, 0.1) == ""
    main()
