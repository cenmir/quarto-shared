--[[
media.lua - Serve each output format the images it needs, from one set of sources.

The sources keep full-resolution images. For HTML every local raster image is
swapped for a WebP at screen resolution, and an animated GIF for a looping,
muted video (WebM, with MP4 for browsers without WebM); for PDF the full-resolution source is
used as is and re-encoded only when LaTeX cannot read it. Converted files live
in <project>/_mediacache/<name>.<key>.<ext>, where the key hashes the source
bytes together with the recipe, so an edited image or a changed recipe misses
the cache and nothing stale is ever served. A hit costs one file read; a miss
runs quarto-shared/quarto_shared/media.py once.

Formats other than HTML also lose what cannot be printed: raw HTML (YouTube
iframes, <video>), video files, animated GIFs, and a figure left with nothing
but its caption. Each strip is logged as a warning, so the warnings list the
elements still waiting for a print version.

Settings, all optional, in _quarto.yml:

    media:
      max-width: 1600   # pixels across of the HTML image
      quality: 82       # lossy WebP quality

Environment: QUARTO_SHARED_ROOT (default ~/quarto-shared) and
QUARTO_SHARED_PYTHON (default python3, which needs Pillow).
]]

-- Bump when media.py changes what it writes. GIFs have their own, so that the
-- switch from GIF to video did not re-encode every other image.
local RECIPE_VERSION = { image = "1", gif = "2" }

local RASTER = { png = true, jpg = true, jpeg = true, gif = true, webp = true,
                 tif = true, tiff = true, bmp = true }
local LATEX_READABLE = { png = true, jpg = true, jpeg = true }
local VIDEO = { mp4 = true, webm = true, mov = true, ogv = true, m4v = true }
-- Every file media.py can leave in the cache, in the order they are looked up.
local CACHED = { "webp", "webm", "png", "keep", "animated" }

local is_html = quarto.doc.is_format("html")
local target = is_html and "html" or "pdf"
local max_width, quality = 1600, 82

local shared_root = os.getenv("QUARTO_SHARED_ROOT")
  or pandoc.path.join({ os.getenv("HOME"), "quarto-shared" })
local python = os.getenv("QUARTO_SHARED_PYTHON") or "python3"
local converter = pandoc.path.join({ shared_root, "quarto_shared", "media.py" })

local project_dir = (quarto.project and quarto.project.directory)
  or pandoc.system.get_working_directory()
local cache_dir = pandoc.path.join({ project_dir, "_mediacache" })
local doc_dir = pandoc.path.directory(quarto.doc.input_file)

local function exists(path)
  local f = io.open(path, "rb")
  if f then f:close() return true end
  return false
end

local function extension(src)
  return (src:match("%.([%w]+)$") or ""):lower()
end

local function is_local(src)
  return not src:match("^%a[%w+.-]*:") and not src:match("^//")
end

-- Image paths are relative to the document; fall back to the working directory.
local function resolve(src)
  if pandoc.path.is_absolute(src) then return src end
  local beside_doc = pandoc.path.normalize(pandoc.path.join({ doc_dir, src }))
  if exists(beside_doc) then return beside_doc end
  if exists(src) then return src end
  return nil
end

local function recipe(path)
  local version = RECIPE_VERSION[extension(path) == "gif" and "gif" or "image"]
  if target == "html" then
    return string.format("v%s html max=%d q=%d", version, max_width, quality)
  end
  return string.format("v%s pdf", version)
end

-- Returns the cache kind ("webp", "png", "keep", "animated") and the cached path.
local function convert(path)
  local f = assert(io.open(path, "rb"))
  local bytes = f:read("a")
  f:close()
  local key = pandoc.utils.sha1(bytes .. "\0" .. recipe(path)):sub(1, 12)
  local name = pandoc.path.split_extension(pandoc.path.filename(path))
  local stem = pandoc.path.join({ cache_dir, name .. "." .. key })

  for _, kind in ipairs(CACHED) do
    if exists(stem .. "." .. kind) then return kind, stem .. "." .. kind end
  end

  local ok, out = pcall(pandoc.pipe, python, {
    converter, "convert", path, stem, "--target", target,
    "--max-width", tostring(max_width), "--quality", tostring(quality),
  }, "")
  if not ok then
    quarto.log.warning("media.lua: could not convert " .. path .. ": " .. tostring(out))
    return "keep", nil
  end
  local kind = out:match("^%s*(%a+)")
  return kind, stem .. "." .. kind
end

local function strip(what, detail)
  quarto.log.warning(string.format("media.lua: stripped %s from %s for %s: %s",
    what, pandoc.path.filename(quarto.doc.input_file), target, detail))
end

local function has_image(blocks)
  if blocks == nil then return false end   -- a float whose only block was stripped
  local found = false
  pandoc.Blocks(blocks):walk({
    Image = function() found = true end,
    CodeBlock = function() found = true end,
  })
  return found
end

-- An animation plays like the GIF it replaces: on its own, silently, in a loop.
local function video(img, webm)
  local function rel(path) return pandoc.path.make_relative(path, doc_dir, true) end
  local mp4 = webm:gsub("%.webm$", ".mp4")
  local style = {}
  for _, side in ipairs({ "width", "height" }) do
    local size = img.attributes[side]
    if size then
      if size:match("^%d+$") then size = size .. "px" end
      table.insert(style, side .. ":" .. size)
    end
  end
  -- A figure's caption has moved to the figure by now; the alt text is what is left.
  local alt = pandoc.utils.stringify(img.caption):gsub('"', "&quot;")
  return pandoc.RawInline("html", string.format(
    '<video class="img-fluid" autoplay loop muted playsinline%s%s>'
      .. '<source src="%s" type="video/webm"><source src="%s" type="video/mp4"></video>',
    alt ~= "" and (' aria-label="' .. alt .. '"') or "",
    #style > 0 and (' style="' .. table.concat(style, ";") .. '"') or "",
    rel(webm), rel(mp4)))
end

local function Image(img)
  local src = img.src
  if not is_local(src) then return nil end
  local ext = extension(src)

  if VIDEO[ext] then
    if is_html then return nil end
    strip("video", src)
    return {}
  end
  if not RASTER[ext] then return nil end   -- SVG and PDF pass through

  local path = resolve(src)
  if not path then return nil end
  if not is_html and LATEX_READABLE[ext] then return nil end   -- full resolution as is

  local kind, cached = convert(path)
  if kind == "animated" then
    if is_html then return nil end
    strip("animated GIF", src)
    return {}
  end
  if kind == "keep" or not cached then return nil end
  if kind == "webm" then return video(img, cached) end

  if is_html then
    img.src = pandoc.path.make_relative(cached, doc_dir, true)
    img.attributes["loading"] = img.attributes["loading"] or "lazy"
  else
    img.src = cached
  end
  return img
end

local function Raw(el)
  if is_html or not el.format:match("^html") then return nil end
  local tag = el.text:match("<(%a+)")
  if tag then   -- closing tags arrive as raw pieces of their own; log only openings
    strip("<" .. tag .. ">", el.text:match('src="([^"]+)"') or "")
  end
  return {}
end

-- A figure whose media was stripped is left holding only its caption. Quarto
-- has already made #fig- divs into FloatRefTarget nodes when this filter runs.
local function Float(float)
  if is_html or float.type ~= "Figure" then return nil end
  if has_image(float.content) then return nil end
  strip("figure", "#" .. float.identifier .. " (its media is HTML-only)")
  return {}
end

local function Meta(meta)
  local settings = meta.media
  if type(settings) == "table" then
    max_width = tonumber(pandoc.utils.stringify(settings["max-width"] or "")) or max_width
    quality = tonumber(pandoc.utils.stringify(settings.quality or "")) or quality
  end
end

-- Meta first, so the settings are known before any image is converted; Raw
-- before Float, so a figure is judged on what is left after its media goes.
return {
  { Meta = Meta },
  { Image = Image, RawBlock = Raw, RawInline = Raw },
  { FloatRefTarget = Float },
}
