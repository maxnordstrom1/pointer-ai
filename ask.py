"""Point the mouse at something, run this, ask a question, get an explanation.

Screenshot includes the cursor, so the model sees what you're pointing at. Hammerspoon passes
--at X,Y --screen X,Y,W,H, which adds a close-up around the cursor and captures the right display,
or --select to let the user drag over an area instead (macOS only).
BACKEND "local" runs via Ollama; "claude" runs via Claude Code on your subscription.
On Windows and Linux, pointer.py runs this instead, and it grabs the screen and cursor position itself.
"""
import base64
import concurrent.futures
import functools
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import urllib.request

BACKEND = "local"  # "local" or "claude"
MODEL = "gemma4"  # any Ollama model with "vision" in `ollama show <model>`
OLLAMA = "http://localhost:11434/api/chat"
# Shortcuts runs with a bare PATH, so fall back to the default install location
CLAUDE = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
SELECT = "--select" in sys.argv  # ⌥⌘D: the user drags over an area instead of pointing
SYSTEM = (
    "You are a helpful assistant. " + (
        "The image is the area of the screen the user selected: that is what they mean. " if SELECT else
        "The first image is the user's screen. If there is a "
        "second image, it is a close-up centered exactly on the mouse cursor: the user is "
        "pointing at whatever is under the cursor at the center of that close-up, so trust it "
        "over the full screen, which is only context. If there is a third image, it is a tight "
        "crop of exactly what is under the cursor: that is what they mean. ") +
    "Answer their question about it in plain "
    "language, briefly (under 150 words). No markdown, but write any math as LaTeX "
    "between $ signs, e.g. $N'(t) = 13$. Copy formulas exactly as written on screen; if you "
    "can't read something clearly, say so instead of guessing. Always reply in the language "
    "of the user's latest question. If that question is exactly \"Explain what I'm pointing "
    "at.\" (sent when they typed nothing), reply in the language of the text on screen "
    "around the cursor instead."
)
ZOOM_W, ZOOM_H = 480, 320  # close-up size in screen points, centered on the cursor
# tight crop of just the spot under the cursor: without it small models drift to whatever stands out
# in the close-up (an icon "explained" as the colourful text beside it). Pixels on Windows/Linux.
TIGHT = 64
MAC = sys.platform == "darwin"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows: no console flashing up from pythonw
WIN = sys.platform == "win32"
WAYLAND = os.environ.get("XDG_SESSION_TYPE") == "wayland"  # apps can't see the cursor position there
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows: no console flashing up from pythonw
# Windows: screenshot of all monitors with the cursor drawn in, then "x,y" of the cursor in it. DPI-aware,
# so pixels match at any scaling. The path comes in $env:AIM_IMG (-Command doesn't pass $args).
WIN_GRAB = r"""
Add-Type -Name D -Namespace W -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
[W.D]::SetProcessDPIAware() | Out-Null
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
$p = [System.Windows.Forms.Cursor]::Position
$c = [System.Windows.Forms.Cursors]::Default  # ponytail: always the arrow, not the cursor's current shape
$c.Draw($g, [System.Drawing.Rectangle]::new($p.X - $b.Left - $c.HotSpot.X, $p.Y - $b.Top - $c.HotSpot.Y, $c.Size.Width, $c.Size.Height))
$bmp.Save($env:AIM_IMG, [System.Drawing.Imaging.ImageFormat]::Png)
"$($p.X - $b.Left),$($p.Y - $b.Top)"
"""
# Windows' built-in OCR (Windows PowerShell 5.1 only: it can reach WinRT). Prints "width height", then
# "left top right bottom text" per line, in pixels.
WIN_OCR = r"""
[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and
  $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait() | Out-Null; $t.Result }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:AIM_IMG)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$res = Await ([Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages().RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
"$($bmp.PixelWidth) $($bmp.PixelHeight)"
foreach ($l in $res.Lines) {
  $r = $l.Words | ForEach-Object { $_.BoundingRect }
  $x0 = [int]($r | ForEach-Object { $_.X } | Measure-Object -Minimum).Minimum
  $y0 = [int]($r | ForEach-Object { $_.Y } | Measure-Object -Minimum).Minimum
  $x1 = [int]($r | ForEach-Object { $_.X + $_.Width } | Measure-Object -Maximum).Maximum
  $y1 = [int]($r | ForEach-Object { $_.Y + $_.Height } | Measure-Object -Maximum).Maximum
  "$x0 $y0 $x1 $y1 $($l.Text)"
}
"""
# Linux: first one installed that works, with the cursor drawn in (ImageMagick's import can't).
# ponytail: whole desktop; on Wayland there's no cursor position, so no close-up
LINUX_GRAB = [["grim", "-c"], ["gnome-screenshot", "-p", "-f"], ["spectacle", "-b", "-n", "-p", "-o"],
              ["scrot", "-p", "-o"], ["import", "-window", "root"]]


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
    """English name of the language ("Swedish"), or "" if unsure."""
    if MAC:
        return vision("lang", text)
    try:
        lang = lingua().detect_language_of(text)
    except ImportError:  # pip install lingua-language-detector (Windows/Linux)
        return ""
    return lang.name.title() if lang else ""


@functools.cache
def lingua():
    from lingua import LanguageDetectorBuilder
    return LanguageDetectorBuilder.from_all_languages().with_minimum_relative_distance(0.05).build()


def read_text(path):
    """Text lines in an image: [[text, x, y, w, h], ...], boxes 0-1 with the origin at the bottom left
    (as macOS Vision gives them). [] if there's no OCR here (Linux without tesseract)."""
    if MAC:
        return json.loads(vision("ocr", path))
    boxes, size = [], (1, 1)
    if WIN:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", WIN_OCR], capture_output=True,
                             env=dict(os.environ, AIM_IMG=path), creationflags=NO_WINDOW).stdout
        rows = out.decode("utf-8-sig", "replace").splitlines()
        size = tuple(map(int, rows[0].split()))
        for row in rows[1:]:
            x0, y0, x1, y1, text = row.split(" ", 4)
            boxes.append((text, int(x0), int(y0), int(x1), int(y1)))
    elif shutil.which("tesseract"):
        out = subprocess.run(["tesseract", path, "-", "tsv"], capture_output=True, text=True, encoding="utf-8").stdout
        lines = {}
        for row in out.splitlines()[1:]:  # level, page, block, paragraph, line, word, left, top, width, height, conf, text
            c = row.split("\t")
            if len(c) < 12:
                continue
            x, y, w, h = map(int, c[6:10])
            if c[0] == "1":
                size = (w, h)
            elif c[0] == "5" and c[11].strip():
                line = lines.setdefault(tuple(c[2:5]), [[], x, y, x + w, y + h])
                line[0].append(c[11])
                line[1:] = min(line[1], x), min(line[2], y), max(line[3], x + w), max(line[4], y + h)
        boxes = [(" ".join(words), *box) for words, *box in lines.values()]
    w, h = size
    return [[t, x0 / w, 1 - y1 / h, (x1 - x0) / w, (y1 - y0) / h] for t, x0, y0, x1, y1 in boxes]


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
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        # our private folder: no project CLAUDE.md or settings, and nothing other users could plant (/tmp is shared)
        cwd=os.path.dirname(image_paths[0]), creationflags=NO_WINDOW,
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


def zoom_rect(mx, my, sx, sy, sw, sh, w=ZOOM_W, h=ZOOM_H):
    """w x h box centered on the cursor, slid inside the screen at the edges."""
    w, h = min(w, sw), min(h, sh)
    x = min(max(mx - w / 2, sx), sx + sw - w)
    y = min(max(my - h / 2, sy), sy + sh - h)
    return x, y, w, h


def grab_mac(img, zoom):
    """Screenshot (+ close-up when Hammerspoon passes the cursor). Returns (images, close-up rect, cursor)."""
    screen, rect, at = [], [], (0, 0)
    if SELECT:  # same crosshair as ⇧⌘4; Esc cancels and leaves no file
        subprocess.run(["screencapture", "-i", "-x", "-t", "jpg", img])
        if not os.path.exists(img):
            return None
        subprocess.run(["sips", "-Z", "1568", img], check=True, capture_output=True)
        return [img], rect, at
    if "--at" in sys.argv and "--screen" in sys.argv:
        at = tuple(map(float, sys.argv[sys.argv.index("--at") + 1].split(",")))
        sx, sy, sw, sh = map(float, sys.argv[sys.argv.index("--screen") + 1].split(","))
        screen = [f"-R{sx:.0f},{sy:.0f},{sw:.0f},{sh:.0f}"]  # the display the cursor is on
        rect = zoom_rect(*at, sx, sy, sw, sh)
    # -C includes the cursor, -x no shutter sound; sips shrinks Retina shots so the model runs faster
    if subprocess.run(["screencapture", "-C", "-x", "-t", "jpg", *screen, img]).returncode != 0:
        subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"])
        show("No Screen Recording permission. Turn on \"Hammerspoon\" (or Terminal, if you ran "
             "this from there) in the settings window that just opened, then try again.")
        return None
    subprocess.run(["sips", "-Z", "1568", img], check=True, capture_output=True)
    if not rect:
        return [img], rect, at
    tight = zoom.replace("zoom", "tight")
    for r, path in ((rect, zoom), (zoom_rect(*at, sx, sy, sw, sh, TIGHT, TIGHT), tight)):
        subprocess.run(["screencapture", "-C", "-x", "-t", "jpg", "-R" + ",".join(f"{v:.0f}" for v in r), path],
                       check=True)
    return [img, zoom, tight], rect, at


def grab_other(img, zoom):
    """Windows/Linux: PNG of the screen, plus a close-up around the cursor when we know where it is.
    Returns (images, close-up rect, cursor), all in screenshot pixels."""
    import tkinter  # ships with Python; reads the cursor position (Linux) and crops PNGs without extra packages
    root = tkinter.Tk()
    root.withdraw()
    try:
        if WIN:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", WIN_GRAB], capture_output=True, text=True,
                               env=dict(os.environ, AIM_IMG=img), creationflags=NO_WINDOW)
            if r.returncode:
                show("Couldn't take a screenshot:\n" + r.stderr.strip())
                return None
            at = tuple(map(int, r.stdout.strip().split(",")))
        else:
            at = root.winfo_pointerxy()
            if not any(shutil.which(c[0]) and subprocess.run(c + [img], capture_output=True).returncode == 0
                       for c in LINUX_GRAB):
                show("Couldn't take a screenshot. Install one of: " + ", ".join(c[0] for c in LINUX_GRAB) + ".")
                return None
        if WAYLAND:
            return [img], [], at
        shot = tkinter.PhotoImage(file=img)
        rect = zoom_rect(*at, 0, 0, shot.width(), shot.height())
        tight = zoom.replace("zoom", "tight")
        for r, path in ((rect, zoom), (zoom_rect(*at, 0, 0, shot.width(), shot.height(), TIGHT, TIGHT), tight)):
            x, y, w, h = map(round, r)
            shot.write(path, format="png", from_coords=(x, y, x + w, y + h))
        return [img, zoom, tight], rect, at
    finally:
        root.destroy()

def main():
    for f in (sys.stdin, sys.stdout):
        f.reconfigure(encoding="utf-8")  # Windows pipes default to a legacy code page
    signal.signal(signal.SIGTERM, lambda *_: sys.exit())  # closing the panel: clean up below
    tmp = tempfile.mkdtemp(prefix="pointer_ai_")  # private (0700): screenshots stay yours
    try:
        run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run(tmp):
    ext = "jpg" if MAC else "png"
    img, zoom = os.path.join(tmp, "pointer_ai." + ext), os.path.join(tmp, "pointer_ai_zoom." + ext)
    shot = (grab_mac if MAC else grab_other)(img, zoom)
    if not shot:
        return
    imgs, rect, at = shot
    ocr = concurrent.futures.ThreadPoolExecutor(1).submit(read_text, imgs[min(1, len(imgs) - 1)])  # runs while the user types
    print("ready", flush=True)  # screenshot taken: Hammerspoon can now show the question box
    converse(imgs, rect, ocr, *at)


def converse(imgs, rect, ocr, mx, my):
    # one-press mode skips the first question; follow-ups keep coming until stdin closes
    question = DEFAULT if "--explain" in sys.argv else read_question()
    try:
        lines = ocr.result()
    except Exception:  # OCR is only a hint: carry on without it
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
    assert zoom_rect(10, 400, 0, 0, 1440, 900, TIGHT, TIGHT) == (0, 368, 64, 64)  # tight crop at the edge
    box = [["far", 0.0, 0.9, 0.1, 0.05], ["b) here", 0.41, 0.45, 0.13, 0.04]]  # Vision boxes, origin bottom left
    assert line_at(box, 0.5, 0.5) == "b) here" and line_at(box, 0.9, 0.1) == ""
    main()
