--- holden-report document class.
-- Inherit from plain, define frames, and render header/footer every page.

local plain = require("classes.plain")

local class = pl.class(plain)
class._name = "holden-report"

-- Default frameset inspired by classes.book, but without twoside logic.
class.defaultFrameset = {
  content = {
    left = "8.3%pw",
    right = "86%pw",
    top = "11.6%ph",
    bottom = "top(footnotes)",
  },
  folio = {
    left = "left(content)",
    right = "right(content)",
    top = "bottom(footnotes)+3%ph",
    bottom = "bottom(footnotes)+5%ph",
  },
  runningHead = {
    left = "left(content)",
    right = "right(content)",
    top = "top(content)-8%ph",
    bottom = "top(content)-3%ph",
  },
  footnotes = {
    left = "left(content)",
    right = "right(content)",
    height = "0",
    bottom = "83.3%ph",
  },
}

function class:_init (options)
  plain._init(self, options)
  self:loadPackage("counters")
  self:loadPackage("masters", {
    {
      id = "default",
      firstContentFrame = "content",
      frames = self.defaultFrameset,
    },
  })
  self:loadPackage("footnotes", {
    insertInto = "footnotes",
    stealFrom = { "content" },
  })
  -- Standard debug package (used to show frames when enabled via env)
  self:loadPackage("debug")

  -- Disable any default folio rendering; footer will be handled by our macro.
  SILE.scratch.counters = SILE.scratch.counters or {}
  SILE.scratch.counters.folio = SILE.scratch.counters.folio or {}
  SILE.scratch.counters.folio.off = true
end

function class:endPage ()
  -- Running header (always, no odd/even switching)
  local rh = SILE.getFrame("runningHead")
  SILE.typesetNaturally(rh, function ()
    SILE.settings:toplevelState()
    SILE.settings:set("current.parindent", SILE.types.node.glue())
    SILE.settings:set("document.lskip", SILE.types.node.glue())
    SILE.settings:set("document.rskip", SILE.types.node.glue())
    if SILE.Commands and SILE.Commands.hrHeader then
      SILE.call("hrHeader")
      SILE.call("par")
    end
  end)

  -- Running footer (page number or other content)
  local ff = SILE.getFrame("folio")
  SILE.typesetNaturally(ff, function ()
    SILE.settings:toplevelState()
    SILE.settings:set("current.parindent", SILE.types.node.glue())
    SILE.settings:set("document.lskip", SILE.types.node.glue())
    SILE.settings:set("document.rskip", SILE.types.node.glue())
    if SILE.Commands and SILE.Commands.runningFooter then
      SILE.call("runningFooter")
      SILE.call("par")
    end
  end)

  -- Optionally overlay frame outlines using the standard debug package
  local dbg = os.getenv("REPORT_DEBUG_BOXES")
  if dbg and dbg ~= "" and dbg ~= "0" and dbg ~= "false" then
    local frames = { "content", "runningHead", "folio", "footnotes" }
    for _, fname in ipairs(frames) do
      pcall(function()
        SILE.call("showframe", { frame = fname })
      end)
    end
  end

  return plain.endPage(self)
end

function class:registerCommands ()
  plain.registerCommands(self)
end

function needspace(height_spec)
  -- Parse the height specification
  local height = SILE.parseComplexFrameDimension(height_spec)
  
  -- Add a custom node to the queue
  local node = {
    type = "needspace_check",
    -- This might be called during processing
    outputYourself = function(self, typesetter, line)
      local remaining = typesetter.frame:bottom() - typesetter.frame.state.cursorY 
      builtin_dump(remaining)
      builtin_dump(height_spec)
      io.write("\n")
      if remaining < height_spec then
        local out = SILE.types.node.glue(height)
        return out
      end
    end
  }

  -- Use pushVertical to add the node
  SILE.typesetter:pushVertical(node)
end

function builtin_dump(val, name, indent, seen)
  -- a really good debug primitive
  name   = name or "<root>"
  indent = indent or ""
  seen   = seen or {}

  if type(val) == "table" then
    if seen[val] then
      print(indent .. name .. " = { <cycle> }")
      return
    end
    seen[val] = true
    print(indent .. name .. " = {")
    for k, v in pairs(val) do
      local key = (type(k) == "string") and k or "["..tostring(k).."]"
      builtin_dump(v, key, indent .. "  ", seen)
    end
    print(indent .. "}")
  elseif type(val) == "function" then
    -- debug.getinfo is part of the standard library
    local info = debug.getinfo(val, "Sn")
    local fn = info.name or "<anonymous>"
    fn = fn .. " (" .. (info.short_src or "?") .. ":" .. (info.linedefined or "?") .. ")"
    print(indent .. name .. " = function: " .. fn)
  else
    print(indent .. name .. " = " .. tostring(val))
  end
end


return class
