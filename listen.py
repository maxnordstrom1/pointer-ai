"""Push-to-talk: records the microphone until a line arrives on stdin (the hotkey was let go),
then prints what was said. Records with ffmpeg and transcribes on device with whisper.cpp.
Works on macOS, Windows and Linux; prints nothing if it heard nothing.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "models", "ggml-base.bin")  # multilingual; ggml-small.bin is better but slower
VAD = os.path.join(HERE, "models", "ggml-silero-v5.1.2.bin")  # skips silence, which Whisper fills with made-up words
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows: no console flashing up
# Hammerspoon and Shortcuts run with a bare PATH, so also look where Homebrew puts things
PATH = os.pathsep.join([os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin"])


def tool(name):
    return shutil.which(name, path=PATH) or name


def mic():
    """ffmpeg input arguments for the system's default microphone."""
    if sys.platform == "darwin":
        return ["-f", "avfoundation", "-i", ":default"]
    if sys.platform == "win32":  # dshow has no "default": take the first audio device it lists
        r = subprocess.run([tool("ffmpeg"), "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        m = re.search(r'"([^"]+)" \(audio\)', r.stderr)
        return ["-f", "dshow", "-i", "audio=" + (m.group(1) if m else "")]
    return ["-f", "pulse", "-i", "default"]  # PulseAudio and PipeWire


def main():
    for f in (sys.stdin, sys.stdout):
        f.reconfigure(encoding="utf-8")
    if not os.path.exists(MODEL):
        print(f"Voice needs a Whisper model at {MODEL}. Download ggml-base.bin from "
              "https://huggingface.co/ggerganov/whisper.cpp/tree/main", flush=True)
        return 1
    with tempfile.TemporaryDirectory(prefix="ai_mouse_") as tmp:  # private (0700) and removed afterwards
        return listen(os.path.join(tmp, "voice.wav"))


def listen(wav):
    try:
        rec = subprocess.Popen([tool("ffmpeg"), "-hide_banner", "-loglevel", "error", *mic(),
                                "-ac", "1", "-ar", "16000", "-y", wav],  # whisper wants 16 kHz mono
                               stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    except OSError:
        print("Voice needs ffmpeg. Install it (macOS: brew install ffmpeg) and try again.", flush=True)
        return 1
    sys.stdin.readline()  # recording until the hotkey is let go
    try:
        rec.communicate(b"q", timeout=5)  # "q" makes ffmpeg finish the file cleanly
    except subprocess.TimeoutExpired:
        rec.kill()
    if rec.returncode:
        print("Couldn't record from the microphone: " + rec.stderr.read().decode(errors="replace").strip()
              + "\nOn macOS, allow Hammerspoon in System Settings → Privacy & Security → Microphone.", flush=True)
        return 1
    try:
        r = subprocess.run([tool("whisper-cli"), "-m", MODEL, "-f", wav, "-l", "auto", "-nt", "-np",
                            *(["--vad", "-vm", VAD] if os.path.exists(VAD) else [])],
                           capture_output=True, text=True, encoding="utf-8", creationflags=NO_WINDOW)
    except OSError:
        print("Voice needs whisper.cpp. Install it (macOS: brew install whisper-cpp) and try again.", flush=True)
        return 1
    # ponytail: whisper writes "[BLANK_AUDIO]" or "(music)" for silence; dropping bracketed tags covers it
    print(re.sub(r"\[[^\]]*\]|\([^)]*\)", "", r.stdout).strip(), flush=True)


if __name__ == "__main__":
    sys.exit(main())
