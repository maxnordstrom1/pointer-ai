-- AI Mouse: ⌥⌘A asks a question about what you're pointing at, ⌥⌘E just explains it
local PYTHON = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
local SCRIPT = os.getenv("HOME") .. "/Desktop/AI_mouse_agent/ask.py"

-- "Breathing" orb, ported from thinking-orbs by Jakub Antalik (MIT):
-- https://github.com/Jakubantalik/thinking-orbs (ring mode, size-20 preset)
local ORB, PAD = 20, 3
local W = ORB + 2 * PAD
local LANES, SEGS, WOB, SPEED = 8, 15, 0.565, 3.78
local RBASE, RDEPTH = 1.7842, 2.7574
local RS = (ORB / 300) ^ 0.6
local R = ORB / 2 * 0.78
local BASE_R = R / (1 + 0.85 * 0.23 * WOB)
local CT, ST = math.cos(0.3), math.sin(0.3)  -- fixed camera tilt
-- Frames are drawn once and looped. The original wave speeds (1.7, 1.1) are
-- nudged to 3 and 2 cycles per loop so the loop has no visible seam.
local FPS, LOOP = 30, 3  -- seconds
local F1, F2 = 2 * math.pi * 3 / (LOOP * SPEED), 2 * math.pi * 2 / (LOOP * SPEED)

local HIDPI = 2  -- frames are drawn at 2x so they stay sharp on Retina screens

local function orbElements(t, dark)
  local glow = { white = dark and 0 or 1, alpha = 0.35 }  -- keeps dots visible on any background
  local dots = {}
  local mid = (LANES - 1) / 2
  for w = 0, LANES - 1 do
    local off = (w - mid) * 0.075
    local edge = math.abs(w - mid) / math.max(1, mid)
    for k = 0, SEGS - 1 do
      local a = k / SEGS * 2 * math.pi
      local wob = (0.16 * math.sin(a * 3 - t * F1 + w * 0.22) + 0.07 * math.sin(a * 5 + t * F2)) * WOB
      local x, y, z = math.cos(a), CT * math.sin(a) + ST * off, -ST * math.sin(a) + CT * off
      local s = BASE_R * (1 + wob) / math.sqrt(x * x + y * y + z * z)
      x, y, z = x * s, y * s, z * s
      local depth = ((y * ST + z * CT) / R + 1) / 2
      local ink = 0.52 - 0.44 * depth + 0.18 * edge
      dots[#dots + 1] = { depth, {
        type = "circle", action = "fill",
        center = { x = (W / 2 + x) * HIDPI, y = (W / 2 - (y * CT - z * ST)) * HIDPI },
        radius = math.max(0.3, (RBASE + RDEPTH * depth) * (1 - 0.25 * edge) * RS) * HIDPI,
        fillColor = { white = dark and 1 - ink or ink, alpha = 0.4 + 0.6 * depth },
        withShadow = true, shadow = { blurRadius = 0.6 * HIDPI, color = glow, offset = { h = 0, w = 0 } },
      } }
    end
  end
  table.sort(dots, function(p, q) return p[1] < q[1] end)  -- far dots first
  local els = {}
  for _, d in ipairs(dots) do els[#els + 1] = d[2] end
  return els
end

local cache = {}
local function frames()
  local dark = hs.host.interfaceStyle() == "Dark"
  local key = dark and "dark" or "light"
  if not cache[key] then
    local c = hs.canvas.new({ x = 0, y = 0, w = W * HIDPI, h = W * HIDPI })
    cache[key] = {}
    for i = 0, FPS * LOOP - 1 do
      c:replaceElements(orbElements(i / FPS * SPEED, dark))
      cache[key][#cache[key] + 1] = c:imageFromCanvas()
    end
    c:delete()
  end
  return cache[key]
end
frames()  -- draw ahead of time so the first use starts instantly

-- Shows the orb just below-right of the cursor and follows it. Returns a function that removes it.
local function spinner()
  local imgs = frames()
  local c = hs.canvas.new({ x = 0, y = 0, w = W, h = W })
  c:level("overlay")
  c:behavior({ "canJoinAllSpaces", "fullScreenAuxiliary" })  -- also show over full-screen apps
  c[1] = { type = "image", image = imgs[1], imageScaling = "scaleProportionally",
           frame = { x = 0, y = 0, w = W, h = W } }
  local start, shown = hs.timer.secondsSinceEpoch(), 1
  local function tick()
    local p = hs.mouse.absolutePosition()
    c:topLeft({ x = p.x + 14, y = p.y + 14 })
    local i = math.floor((hs.timer.secondsSinceEpoch() - start) * FPS) % #imgs + 1
    if i ~= shown then c[1].image = imgs[i]; shown = i end
  end
  tick()
  c:show()
  local timer = hs.timer.doEvery(1 / 60, tick)  -- 60 fps keeps the cursor-follow smooth
  return function() timer:stop(); c:delete() end
end

-- Top-left for a w×h box beside the cursor point p, flipped to stay on p's screen
local function besideCursor(p, w, h)
  local f = hs.mouse.getCurrentScreen():frame()
  local x, y = p.x + 16, p.y + 16
  if x + w > f.x + f.w then x = math.max(f.x, p.x - 16 - w) end
  if y + h > f.y + f.h then y = math.max(f.y, p.y - 16 - h) end
  return { x = x, y = y, w = w, h = h }
end

-- Soft monochrome look to match the orb; follows the system light/dark setting like the orb does
local STYLE = [[<!doctype html><meta charset="utf-8"><style>
:root { color-scheme: light dark; --bg: rgba(250,250,250,.97); --ink: rgba(0,0,0,.74); --dim: rgba(0,0,0,.35); --edge: rgba(0,0,0,.08) }
@media (prefers-color-scheme: dark) { :root { --bg: rgba(24,24,26,.97); --ink: rgba(255,255,255,.80); --dim: rgba(255,255,255,.38); --edge: rgba(255,255,255,.10) } }
html, body { margin: 0; height: 100%; background: transparent; overflow: hidden }
.box { box-sizing: border-box; height: 100%; border-radius: 14px; background: var(--bg); color: var(--ink);
       box-shadow: inset 0 0 0 .5px var(--edge); font: 12.5px/1.5 -apple-system, sans-serif;
       animation: in .35s cubic-bezier(.2,.8,.2,1) }
@keyframes in { from { opacity: 0; transform: scale(.94) } }
@keyframes breathe { 50% { opacity: .25; transform: scale(.7) } }
::-webkit-scrollbar { width: 6px } ::-webkit-scrollbar-thumb { background: var(--dim); border-radius: 3px }
::placeholder { color: var(--dim) }
</style><script>const post = m => webkit.messageHandlers.aimouse.postMessage(m)</script>]]

local panel, follow, escKey, onClose
local function closePanel()
  if follow then follow:stop(); follow = nil end
  if panel then panel:delete(); panel = nil end
  if escKey then escKey:delete(); escKey = nil end
  if onClose then local f = onClose; onClose = nil; f() end
end

-- Panel that rides beside the cursor like the orb. Hold ⌥ to park it (to select or scroll with the mouse);
-- it also stays put while the cursor is over it. Page posts {h=} to resize; anything else goes to onMsg.
local function openPanel(html, w, h, onMsg, closed)
  closePanel()
  local size = { w = w, h = h }
  local uc = hs.webview.usercontent.new("aimouse")
  uc:setCallback(function(msg)
    if msg.body.h then size.h = math.min(msg.body.h, 360) else onMsg(msg.body) end
  end)
  panel = hs.webview.new(besideCursor(hs.mouse.absolutePosition(), w, h), {}, uc)
    :windowStyle({ "borderless" })
    :transparent(true)
    :allowTextEntry(true)  -- lets it take keyboard focus
    :shadow(true)
    :level(hs.drawing.windowLevels.floating)
    :behaviorAsLabels({ "canJoinAllSpaces", "fullScreenAuxiliary" })  -- also over full-screen apps
    :html(STYLE .. html)
    :show()
  panel:hswindow():focus()
  onClose = closed
  escKey = hs.hotkey.bind({}, "escape", closePanel)  -- ponytail: swallows Esc everywhere while a panel is open
  follow = hs.timer.doEvery(1 / 60, function()
    local p, f = hs.mouse.absolutePosition(), panel:frame()
    local over = p.x >= f.x and p.x <= f.x + f.w and p.y >= f.y and p.y <= f.y + f.h
    if over or hs.eventtap.checkKeyboardModifiers().alt then
      if f.h ~= size.h then panel:frame({ x = f.x, y = f.y, w = size.w, h = size.h }) end
    else
      panel:frame(besideCursor(p, size.w, size.h))
    end
  end)
end

local function htmlEscape(s)
  return (s:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"))
end

-- Answer panel: the whole thread, newest at the bottom, plus a follow-up line when onAsk is given.
-- Select with the mouse (hold ⌥ first) or ⌘C to copy, everything if nothing is selected. Esc closes.
local function showAnswer(thread, onAsk, closed)
  local parts = {}
  for _, t in ipairs(thread) do
    if t.q then parts[#parts + 1] = '<p class="q">' .. htmlEscape(t.q) .. "</p>" end
    parts[#parts + 1] = "<p>" .. htmlEscape(t.a) .. "</p>"
  end
  local sent = false
  openPanel([[<style>
.box { display: flex; flex-direction: column }
#b { flex: 1; overflow: auto; padding: 0 14px; white-space: pre-wrap; cursor: text }
p { margin: 10px 0 } .q { color: var(--dim) }
.ask { flex: none; height: 34px; display: flex; align-items: center; gap: 9px; padding: 0 14px;
       box-shadow: inset 0 .5px 0 var(--edge) }
i { flex: none; width: 5px; height: 5px; border-radius: 50%; background: var(--dim); animation: breathe 2.4s ease-in-out infinite }
input { flex: 1; border: 0; outline: 0; background: none; color: inherit; font: inherit }
</style><div class="box"><div id="b">]] .. table.concat(parts) .. [[</div>]] ..
    (onAsk and [[<div class="ask"><i></i><input id="q" placeholder="Follow up…"></div>]] or "") .. [[</div><script>
post({ h: b.scrollHeight + (window.q ? 34 : 0) })  // grow to fit, up to 360px, then scroll
b.scrollTop = b.scrollHeight  // newest answer in view
if (window.q) { q.focus(); q.addEventListener("keydown", e => { if (e.key === "Enter" && q.value.trim()) post({ q: q.value }) }) }
addEventListener("keydown", e => {
  if (e.metaKey && e.key === "c") post({ copy: String(getSelection()) || b.innerText })
  if (e.metaKey && e.key === "a" && document.activeElement !== window.q) { e.preventDefault(); getSelection().selectAllChildren(b) }
})
</script>]], 340, 40,
    function(m)
      if m.copy then hs.pasteboard.setContents(m.copy)
      elseif m.q and not sent then
        sent = true
        hs.timer.doAfter(0, function() closePanel(); onAsk(m.q) end)  -- not from inside the panel's own callback
      end
    end,
    function() if not sent and closed then closed() end end)
end

-- Question box by the cursor. Calls done(question), or done(nil) on Esc.
local function askQuestion(done)
  local sent = false
  openPanel([[<style>
.box { display: flex; align-items: center; gap: 9px; padding: 0 14px }
i { flex: none; width: 6px; height: 6px; border-radius: 50%; background: var(--ink); animation: breathe 2.4s ease-in-out infinite }
input { flex: 1; border: 0; outline: 0; background: none; color: inherit; font: inherit }
</style><div class="box"><i></i><input id="q" placeholder="Ask about this… or just press ↵" autofocus></div><script>
q.focus()
q.addEventListener("keydown", e => { if (e.key === "Enter") post({ q: q.value }) })
</script>]], 300, 38,
    function(m)
      if sent then return end
      sent = true
      hs.timer.doAfter(0, function()  -- not from inside the panel's own callback
        closePanel()
        done(m.q ~= "" and m.q or "Explain what I'm pointing at.")
      end)
    end,
    function() if not sent then done(nil) end end)
end

-- One conversation per hotkey press: same screenshot, follow-ups until Esc
local function aiMouse(explain)
  closePanel()
  local out, err, ready, stop, task = "", "", false, nil, nil
  local thread, pending = {}, explain and "Explain what I'm pointing at." or nil
  local function hide() if stop then stop(); stop = nil end end
  local function think() if not stop then stop = spinner() end end
  local function ask(q) pending = q; task:setInput(q .. "\n"); think() end
  local p, f = hs.mouse.absolutePosition(), hs.mouse.getCurrentScreen():fullFrame()
  local args = { SCRIPT, "--at", ("%.0f,%.0f"):format(p.x, p.y), "--screen", ("%.0f,%.0f,%.0f,%.0f"):format(f.x, f.y, f.w, f.h) }
  if explain then args[#args + 1] = "--explain" end
  task = hs.task.new(PYTHON, function(code)
      hide()
      local msg = out:match("^%s*(.-)%s*$")  -- leftovers, e.g. the no-permission message
      if msg == "" and code ~= 0 and code ~= 15 then msg = "AI Mouse crashed:\n" .. err end  -- 15: we ended it
      if msg ~= "" then showAnswer({ { a = msg } }) end
    end,
    function(_, so, se)
      out, err = out .. (so or ""), err .. (se or "")
      if not ready and out:find("^ready\n") then  -- screenshot taken, safe to draw on screen
        ready, out = true, out:sub(7)
        if explain then think() else
          askQuestion(function(q) if q then ask(q) else task:terminate() end end)
        end
      end
      local a, rest = out:match("^(.-)\n\30\n(.*)$")  -- \30 = END marker from ask.py
      if ready and a then
        out = rest
        hide()
        thread[#thread + 1] = { q = pending, a = a:match("^%s*(.-)%s*$") }
        showAnswer(thread, ask, function() task:terminate() end)
      end
      return true
    end,
    args)
  task:start()
end

hs.hotkey.bind({ "alt", "cmd" }, "A", function() aiMouse(false) end)
hs.hotkey.bind({ "alt", "cmd" }, "E", function() aiMouse(true) end)
