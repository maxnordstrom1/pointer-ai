-- AI Mouse: ⌥⌘A asks a question about what you're pointing at, ⌥⌘E just explains it, hold ⌥⌘S to speak it
local PYTHON = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
local DIR = os.getenv("HOME") .. "/Desktop/AI_mouse_agent/"
local SCRIPT = DIR .. "ask.py"
local LISTEN = os.getenv("HOME") .. "/Desktop/AI_mouse_agent/listen.py"

-- Reload Hammerspoon when this file changes, so edits take effect without a manual reload
AIMouseWatcher = hs.pathwatcher.new(DIR, function(paths)
  for _, p in ipairs(paths) do if p:match("%.lua$") then hs.reload(); return end end
end):start()  -- global so it isn't garbage-collected

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

-- Each dot: { depth, x, y, radius, ink, alpha }
local function ringDots(t)
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
      dots[#dots + 1] = { depth, W / 2 + x, W / 2 - (y * CT - z * ST),
        math.max(0.3, (RBASE + RDEPTH * depth) * (1 - 0.25 * edge) * RS), 0.52 - 0.44 * depth + 0.18 * edge, 0.4 + 0.6 * depth }
    end
  end
  return dots
end

-- "Listening": a waveform rolls through the rings of a dotted sphere (thinking-orbs' wave mode, size-20 preset)
local WAVE_R, RINGS, LON, WSPEED = ORB / 2 * 0.874, 5, 13, 3.998
local WRBASE, WRDEPTH = 0.6 * 1.6, 1.7 * 1.6
local WCT, WST = math.cos(0.38), math.sin(0.38)
-- Loops after a 3/4 turn (its 8- and 12-dot rings look the same every quarter turn);
-- the wave speeds (2.1, 1.27) are nudged to 9 and 5 cycles per loop
local WLOOP = 1.5 * math.pi / 0.18
local W1, W2 = 2 * math.pi * 9 / WLOOP, 2 * math.pi * 5 / WLOOP
local function waveDots(t)
  local dots = {}
  local cy, sy = math.cos(t * 0.18), math.sin(t * 0.18)
  for ri = 0, RINGS do
    local lat = -math.pi / 2 + ri / RINGS * math.pi
    local w = 0.62 * math.sin(t * W1 - ri * 0.52) + 0.38 * math.sin(t * W2 + ri * 0.83)
    local rr, crest = WAVE_R * (0.88 + 0.105 * w), math.max(0, w)
    local n = math.max(1, math.floor(math.abs(math.cos(lat)) * LON + 0.5))
    for j = 0, n - 1 do
      local lon = j / n * 2 * math.pi
      local x, y, z = math.cos(lat) * math.cos(lon) * rr, math.sin(lat) * rr, math.cos(lat) * math.sin(lon) * rr
      x, z = x * cy + z * sy, -x * sy + z * cy
      local depth = ((y * WST + z * WCT) / WAVE_R + 1) / 2
      dots[#dots + 1] = { depth, W / 2 + x, W / 2 - (y * WCT - z * WST),
        math.max(0.3, (WRBASE + WRDEPTH * depth) * (1 + 0.4 * crest) * RS), 0.66 - 0.56 * depth - 0.1 * crest, 1 }
    end
  end
  return dots
end

local function orbElements(dots, dark)
  local glow = { white = dark and 0 or 1, alpha = 0.35 }  -- keeps dots visible on any background
  table.sort(dots, function(p, q) return p[1] < q[1] end)  -- far dots first
  local els = {}
  for _, d in ipairs(dots) do
    els[#els + 1] = {
      type = "circle", action = "fill",
      center = { x = d[2] * HIDPI, y = d[3] * HIDPI }, radius = d[4] * HIDPI,
      fillColor = { white = dark and 1 - d[5] or d[5], alpha = d[6] },
      withShadow = true, shadow = { blurRadius = 0.6 * HIDPI, color = glow, offset = { h = 0, w = 0 } },
    }
  end
  return els
end

-- dots, t covered by one loop, frames in it
local MODES = { thinking = { ringDots, LOOP * SPEED, FPS * LOOP },
                listening = { waveDots, WLOOP, math.floor(FPS * WLOOP / WSPEED + 0.5) } }
local cache = {}
local function frames(mode)
  local dark = hs.host.interfaceStyle() == "Dark"
  local key = mode .. (dark and "dark" or "light")
  if not cache[key] then
    local dots, span, n = table.unpack(MODES[mode])
    local c = hs.canvas.new({ x = 0, y = 0, w = W * HIDPI, h = W * HIDPI })
    cache[key] = {}
    for i = 0, n - 1 do
      c:replaceElements(orbElements(dots(i / n * span), dark))
      cache[key][#cache[key] + 1] = c:imageFromCanvas()
    end
    c:delete()
  end
  return cache[key]
end
frames("thinking"); frames("listening")  -- draw ahead of time so the first use starts instantly

-- Shows the orb just below-right of the cursor and follows it. Returns a function that removes it.
local function spinner(listening)
  local imgs = frames(listening and "listening" or "thinking")
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

-- Panel pages live in ui/ (shared with aimouse.py on Windows and Linux)
local function ui(name)
  local f = assert(io.open(DIR .. "ui/" .. name .. ".html"))
  local s = f:read("a")
  f:close()
  return s
end

local panel, follow, escKey, scrollTap, onClose
local function closePanel()
  if follow then follow:stop(); follow = nil end
  if scrollTap then scrollTap:stop(); scrollTap = nil end
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
    if msg.body.h then size.h, size.overflow = math.min(msg.body.h, 360), msg.body.h > 360
    else onMsg(msg.body) end
  end)
  panel = hs.webview.new(besideCursor(hs.mouse.absolutePosition(), w, h), {}, uc)
    :windowStyle({ "borderless" })
    :transparent(true)
    :allowTextEntry(true)  -- lets it take keyboard focus
    :shadow(true)
    :level(hs.drawing.windowLevels.floating)
    :behaviorAsLabels({ "canJoinAllSpaces", "fullScreenAuxiliary" })  -- also over full-screen apps
    :html(ui("style") .. html)
    :show()
  panel:hswindow():focus()
  onClose = closed
  escKey = hs.hotkey.bind({}, "escape", closePanel)  -- ponytail: swallows Esc everywhere while a panel is open
  -- The panel rides on the cursor, so the scroll wheel would always hit the window underneath.
  -- While the conversation overflows the panel, scroll it instead (it scrolls the #b element).
  scrollTap = hs.eventtap.new({ hs.eventtap.event.types.scrollWheel }, function(e)
    if not size.overflow then return false end
    local dy = e:getProperty(hs.eventtap.event.properties.scrollWheelEventPointDeltaAxis1)
    panel:evaluateJavaScript("b.scrollBy(0, " .. -dy .. ")")
    return true
  end):start()
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

-- Text for JavaScript: a JSON string literal
local function js(s) return hs.json.encode({ s }) .. "[0]" end

-- Conversation panel: the thread so far, plus a follow-up line when onAsk is given. Returns a function
-- that runs JavaScript in it (queued until the page has loaded) to add a question, type text, finish.
-- Select with the mouse (hold ⌥ first) or ⌘C to copy, everything if nothing is selected. Esc closes.
local function showThread(thread, onAsk, closed)
  local parts = {}
  for _, t in ipairs(thread) do
    if t.q then parts[#parts + 1] = '<p class="q">' .. htmlEscape(t.q) .. "</p>" end
    parts[#parts + 1] = "<p>" .. htmlEscape(t.a) .. "</p>"
  end
  local loaded, queued = false, {}
  local html = ui("thread"):gsub("{{THREAD}}", function() return table.concat(parts) end)
  if not onAsk then html = html:gsub("<!%-%-ask%-%->.-<!%-%-/ask%-%->", "") end
  openPanel(html, 340, 40,
    function(m)
      if m.ready then
        loaded = true
        for _, code in ipairs(queued) do panel:evaluateJavaScript(code) end
        queued = {}
      elseif m.copy then
        if m.copy == "" then  -- nothing selected: the plain-text thread, with unrendered math
          local raw = {}
          for _, t in ipairs(thread) do if t.q then raw[#raw + 1] = t.q end; raw[#raw + 1] = t.a end
          m.copy = table.concat(raw, "\n\n")
        end
        hs.pasteboard.setContents(m.copy)
      elseif m.q and onAsk then onAsk(m.q) end
    end,
    closed)
  local mine = panel
  return function(code)
    if mine ~= panel then return end  -- closed or replaced
    if loaded then panel:evaluateJavaScript(code) else queued[#queued + 1] = code end
  end
end

-- Splits off a trailing incomplete UTF-8 character (a pipe read can end mid-character)
local function utf8Split(s)
  for k = #s, math.max(1, #s - 3), -1 do
    local c = s:byte(k)
    if c < 0x80 then break end
    if c >= 0xC0 then
      local len = c >= 0xF0 and 4 or c >= 0xE0 and 3 or 2
      if #s - k + 1 < len then return s:sub(1, k - 1), s:sub(k) end
      break
    end
  end
  return s, ""
end

-- Question box by the cursor. Calls done(question), or done(nil) on Esc.
local function askQuestion(done)
  local sent = false
  openPanel(ui("ask"), 300, 38,
    function(m)
      if sent or not m.q then return end
      sent = true
      hs.timer.doAfter(0, function()  -- not from inside the panel's own callback
        closePanel()
        done(m.q ~= "" and m.q or "Explain what I'm pointing at.")
      end)
    end,
    function() if not sent then done(nil) end end)
end

-- One conversation per hotkey press: same screenshot, follow-ups until Esc. ask.py streams each answer
-- in pieces and ends it with \30 (END). With voice, the first question is spoken instead of typed:
-- listen.py records until the returned function is called (hotkey let go), then it's asked.
local function aiMouse(explain, voice, select)
  closePanel()
  local out, err, ready, stop, task, view = "", "", false, nil, nil, nil
  local thread, cur = {}, explain and { q = "Explain what I'm pointing at.", a = "" } or nil
  local function hide() if stop then stop(); stop = nil end end
  local function ended() if task:isRunning() then task:terminate() end end
  local function ask(q)
    cur = { q = q, a = "" }
    task:setInput(q .. "\n")
    -- orb until the panel exists, but not before the screenshot, or it would be in it
    if view then view("addQ(" .. js(q) .. ")") elseif ready then hide(); stop = spinner() end  -- thinking, not listening
  end
  local function got(text, finished)
    if not view then
      hide()
      view = showThread(thread, ask, ended)
      view("addQ(" .. js(cur.q) .. ")")
    end
    if text ~= "" then cur.a = cur.a .. text; view("addText(" .. js(text) .. ")") end
    if finished then
      thread[#thread + 1] = { q = cur.q, a = cur.a:match("^%s*(.-)%s*$") }
      cur = nil
      view("finish()")
    end
  end
  local p, f = hs.mouse.absolutePosition(), hs.mouse.getCurrentScreen():fullFrame()
  local args = { SCRIPT, "--at", ("%.0f,%.0f"):format(p.x, p.y), "--screen", ("%.0f,%.0f,%.0f,%.0f"):format(f.x, f.y, f.w, f.h) }
  if explain then args[#args + 1] = "--explain" end
  if select then args[#args + 1] = "--select" end
  task = hs.task.new(PYTHON, function(code)
      hide()
      local msg = not ready and out:match("^%s*(.-)%s*$") or ""  -- e.g. the no-permission message
      if msg == "" and code ~= 0 and code ~= 15 then msg = "AI Mouse crashed:\n" .. err end  -- 15: we ended it
      if msg ~= "" then showThread({ { a = msg } }) end
    end,
    function(_, so, se)
      out, err = out .. (so or ""), err .. (se or "")
      if not ready and out:find("^ready\n") then  -- screenshot taken, safe to draw on screen
        ready, out = true, out:sub(7)
        if explain or voice then stop = stop or spinner(voice and not cur) else  -- no question yet: still listening
          askQuestion(function(q) if q then ask(q) else task:terminate() end end)
        end
      end
      if ready and cur then
        local i = out:find("\30", 1, true)
        while i and cur do
          got(out:sub(1, i - 1), true)
          out = (out:sub(i + 1):gsub("^\n", ""))
          i = out:find("\30", 1, true)
        end
        if cur and out ~= "" then
          local text
          text, out = utf8Split(out)
          if text ~= "" then got(text, false) end
        end
      end
      return true
    end,
    args)
  task:start()
  if not voice then return end
  -- without a streaming callback listen.py saw stdin closed at once and stopped recording, so stdout is collected there
  local heard = ""
  local listen = hs.task.new(PYTHON, function(code, so)
    local said = (heard .. (so or "")):match("^%s*(.-)%s*$")
    if code == 0 and said ~= "" and task:isRunning() then return ask(said) end
    hide(); ended()  -- heard nothing, ask.py already quit, or an error (no mic permission, no whisper)
    if code ~= 0 and said ~= "" then showThread({ { a = said } }) end
  end, function(_, so) heard = heard .. (so or ""); return true end, { LISTEN })
  listen:start()
  return function() listen:setInput("\n") end
end

hs.hotkey.bind({ "alt", "cmd" }, "A", function() aiMouse(false) end)
hs.hotkey.bind({ "alt", "cmd" }, "E", function() aiMouse(true) end)
-- Drag over an area (like ⇧⌘4), then ask about it; leave the question empty to get it explained
-- waits for ⌥⌘ to be let go: in the crosshair, a held ⌥ grows the selection from its center
local selectWait  -- kept so the timer isn't garbage collected while it waits
hs.hotkey.bind({ "alt", "cmd" }, "D", function()
  selectWait = hs.timer.waitUntil(function() local m = hs.eventtap.checkKeyboardModifiers(); return not (m.alt or m.cmd) end,
    function() aiMouse(false, false, true) end, 0.02)
end)
-- Hold ⌥⌘S and speak your question; let go to send it
local stopListening
hs.hotkey.bind({ "alt", "cmd" }, "S",
  function() stopListening = aiMouse(false, true) end,
  function() if stopListening then stopListening(); stopListening = nil end end)
