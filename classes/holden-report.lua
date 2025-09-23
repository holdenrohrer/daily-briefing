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

  -- Disable any default folio rendering; footer will be handled by our macro.
  SILE.scratch.counters = SILE.scratch.counters or {}
  SILE.scratch.counters.folio = SILE.scratch.counters.folio or {}
  SILE.scratch.counters.folio.off = true
end

function class:endPage ()
  -- Finalize sectionbox vertical rules for this page (draw once per page)
  do
    local folio = (SILE and SILE.scratch and SILE.scratch.counters and SILE.scratch.counters.folio and SILE.scratch.counters.folio.value) or 1
    local st = SILE.scratch and SILE.scratch.__sectionbox_state
    if st and st[folio] then
      local optsmap = SILE.scratch.__sectionbox_opts or {}
      for uid, bs in pairs(st[folio]) do
        local opts = optsmap[uid] or {}
        local bw = opts.bw or 1
        local ex = opts.ex or 0
        local color = opts.color or "#c9b458"
        if bs.xL and bs.xR and bs.yTop and bs.yBottom and bs.yBottom > bs.yTop then
          SILE.outputter:pushColor(color)
          SILE.outputter:drawRule(bs.xL, bs.yTop - ex, bw, (bs.yBottom - bs.yTop) + 2*ex)
          SILE.outputter:drawRule(bs.xR - bw, bs.yTop - ex, bw, (bs.yBottom - bs.yTop) + 2*ex)
          SILE.outputter:popColor()
        end
      end
      st[folio] = nil
    end
  end

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

  return plain.endPage(self)
end

function class:registerCommands ()
  plain.registerCommands(self)
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
