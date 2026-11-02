# AI Mouse

Point at anything on your screen, press a hotkey, ask a question, and get a plain-language explanation in a popup.

It takes a screenshot of the screen your mouse is on, plus a close-up centred on the cursor, so the AI knows exactly what you're pointing at. Leave the question box empty to just get "what is this?"

## Requirements

- macOS
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
   python3 ~/Desktop/AI_mouse_agent/ask.py
   ```

   Type your question and press Return (empty = just explain). The answer prints in Terminal.

   The first time, macOS asks for **Screen Recording** permission. Allow it in System Settings → Privacy & Security → Screen Recording, then run it again.

3. **Add hotkeys (⌥⌘A, ⌥⌘E) with [Hammerspoon](https://www.hammerspoon.org).** It works in every app, including Chrome and full-screen apps, which the Shortcuts app's hotkeys don't.

   ```sh
   brew install --cask hammerspoon
   ```

   Put this line in `~/.hammerspoon/init.lua`, then open Hammerspoon:

   ```lua
   dofile(os.getenv("HOME") .. "/Desktop/AI_mouse_agent/hammerspoon.lua")
   ```

   (If your Python or this folder is somewhere else, update `PYTHON` and `SCRIPT` at the top of `hammerspoon.lua`.) Hammerspoon reloads by itself whenever `hammerspoon.lua` changes. Give Hammerspoon **Accessibility** and **Screen Recording** permission, and turn on "Launch Hammerspoon at login" in its settings.

## Usage

Hover over something, then:

- **⌥⌘A**: a small question box appears by the cursor. Type a question (or leave it empty) and press Return. Esc cancels.
- **⌥⌘E**: skip the question and just explain what you're pointing at.

A small animated orb follows your cursor while the AI works, then the answer appears in a panel that follows the cursor. Math is shown as proper formulas (needs internet; offline you see the raw LaTeX). Type a follow-up at the bottom and press Return to keep asking about the same screenshot. Press ⌘C to copy it all, or hold ⌥ to park the panel so you can move onto it to select text or scroll. Esc closes it.

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
