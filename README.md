# Pointer AI

Point at anything on your screen, press a hotkey, ask a question, and get a plain-language explanation in a popup.

It takes a screenshot of the screen your mouse is on, plus a close-up centred on the cursor and a tight crop of just what's under it, so the AI knows exactly what you're pointing at. Leave the question box empty to just get "what is this?" It answers in the language you ask in, or, with no question, the language of the text you're pointing at.

## Requirements

- macOS, Windows or Linux (see [Windows and Linux](#windows-and-linux) for the extra setup)
- Python 3
- One of:
  - **Local mode (default):** [Ollama](https://ollama.com) with a vision model. The default is `gemma4`.
  - **Claude mode:** [Claude Code](https://claude.com/claude-code), signed in with your Claude subscription.

No extra Python packages are needed.

## Setup

1. **Choose a mode.** At the top of `ask.py`:

   ```python
   BACKEND = "local"   # or "claude"
   MODEL = "gemma4"    # local mode only
   ```

   For local mode, make sure the model is downloaded and Ollama is running:

   ```sh
   ollama pull gemma4
   ```

2. **Try it from Terminal:**

   ```sh
   python3 ~/Desktop/pointer-ai/ask.py
   ```

   Type your question and press Return (empty = just explain). The answer prints in Terminal.

   The first time, macOS asks for **Screen Recording** permission. Allow it in System Settings → Privacy & Security → Screen Recording, then run it again.

3. **Add hotkeys (⌥⌘A, ⌥⌘E) with [Hammerspoon](https://www.hammerspoon.org).** It works in every app, including Chrome and full-screen apps, which the Shortcuts app's hotkeys don't.

   ```sh
   brew install --cask hammerspoon
   ```

   Put this line in `~/.hammerspoon/init.lua`, then open Hammerspoon:

   ```lua
   dofile(os.getenv("HOME") .. "/Desktop/pointer-ai/hammerspoon.lua")
   ```

   (If your Python or this folder is somewhere else, update `PYTHON` and `SCRIPT` at the top of `hammerspoon.lua`.) Hammerspoon reloads by itself whenever `hammerspoon.lua` changes. Give Hammerspoon **Accessibility** and **Screen Recording** permission, and turn on "Launch Hammerspoon at login" in its settings.

## Windows and Linux

`pointer.py` does what Hammerspoon does on the Mac: the same hotkeys, orb, cursor-following panel, math, follow-ups and copy. Choose the mode in `ask.py` as in step 1 above, then:

```sh
pip install -r requirements.txt
python pointer.py
```

Leave it running. **Win+Alt+A** asks, **Win+Alt+E** explains and holding **Win+Alt+S** lets you speak (Super+Alt on Linux; voice needs the setup under [Voice](#voice)); Ctrl+C copies and Alt parks the panel. To start it at login, put a shortcut to `pythonw C:\path\to\pointer.py` in the folder that `shell:startup` opens (Windows), or add it to your desktop's startup apps (Linux).

- **Windows** needs nothing else. Text recognition and screenshots use what's built into Windows.
- **Linux** needs `python3-tk`, `xclip` (for copying) and a screenshot tool: `gnome-screenshot`, `spectacle` (KDE), `scrot` or ImageMagick's `import`; `grim` on Sway/Hyprland. Install `tesseract` too, so the model is told which text sits under the cursor.
- **Linux on Wayland** (the default on Ubuntu and Fedora) doesn't let apps see the cursor or grab global hotkeys. Bind your desktop's own shortcuts to `python3 /path/to/pointer.py --ask` and `--explain` instead (no voice: desktop shortcuts can't tell when you let go). The panel then opens where the desktop puts it and stays there, and there's no close-up. For the full experience, log in to an X11 ("Xorg") session.

## Usage

Hover over something, then:

- **⌥⌘A**: a small question box appears by the cursor. Type a question (or leave it empty) and press Return. Esc cancels.
- **⌥⌘E**: skip the question and just explain what you're pointing at.
- **⌥⌘D**: drag over an area (like ⇧⌘4, Esc cancels), then ask about it. Leave the question empty to get it explained.
- **Hold ⌥⌘S**: speak your question, let go to send it (see Voice below).

A small animated orb follows your cursor while the AI works, then the answer types itself out in a panel that follows the cursor, as the AI writes it. Math is shown as proper formulas (needs internet; offline you see the raw LaTeX). Type a follow-up at the bottom and press Return to keep asking about the same screenshot; the panel stays open and the conversation builds up in it. Press ⌘C to copy it all, Once the conversation is longer than the panel, your scroll wheel (or ↑/↓) scrolls it. Hold ⌥ to park the panel so you can move onto it to select text. Esc closes it.

## Voice

Hold ⌥⌘S (Win+Alt+S on Windows and Linux), say your question, and let go. `listen.py` records the microphone with ffmpeg and turns your speech into text on your own computer with [whisper.cpp](https://github.com/ggml-org/whisper.cpp), in whatever language you speak. One-time setup:

```sh
brew install ffmpeg whisper-cpp
mkdir -p ~/Desktop/pointer-ai/models
curl -L -o ~/Desktop/pointer-ai/models/ggml-small.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
curl -L -o ~/Desktop/pointer-ai/models/ggml-silero-v5.1.2.bin https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin
```

The first time, macOS asks to let Hammerspoon use the microphone. On Windows and Linux, install ffmpeg and whisper.cpp (`whisper-cli` on your PATH) and download the same two files into `models/`. Windows records from the first microphone ffmpeg lists; Linux from the default PulseAudio/PipeWire input. For faster but less accurate recognition, download `ggml-base.bin` instead and change `MODEL` in `listen.py`.

## Modes compared

|                    | Local (`gemma4`)                    | Claude                                   |
| ------------------ | ----------------------------------- | ---------------------------------------- |
| Cost               | Free                                | Counts toward your subscription's usage limits |
| Privacy            | Nothing leaves your Mac             | Screenshot is sent to Anthropic          |
| Speed              | About 10 s (first run loads the model) | About 15 s (Claude Code starts up each time) |
| Memory             | About 10 GB while loaded            | Minimal                                  |
| Answer quality     | Good for simple questions           | Better for harder questions              |

## Tweaks

- **Smaller local model:** if your Mac feels slow, try `ollama pull qwen2.5vl:3b` or `moondream` and change `MODEL`. Text-only models such as `llama3.1` or `qwen2.5` won't work. Check for "vision" in `ollama show <model>`.
- **Smarter local answers:** set `"think": False` to `True` in `ask_model`. Answers get slower but better.
- **Bigger or smaller close-up:** change `ZOOM_W, ZOOM_H` in `ask.py`. Smaller focuses the AI more tightly on the cursor; bigger gives it more surroundings.
- **Longer answers:** edit the "under 150 words" line in `SYSTEM`.

## Troubleshooting

- **"could not create image from display":** the app running the script (Terminal or Shortcuts) needs Screen Recording permission.
- **"Couldn't reach Ollama":** start it with `ollama serve`, or open the Ollama app.
- **"Claude Code failed":** run `claude` once in Terminal to check that you're signed in.

## Credits

The loading orb is the "breathing" animation from [thinking-orbs](https://github.com/Jakubantalik/thinking-orbs) by Jakub Antalik (MIT), ported to Hammerspoon.
