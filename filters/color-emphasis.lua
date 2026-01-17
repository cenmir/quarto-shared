-- Set of known color class names
local color_classes = {
    red = true, blue = true, green = true,
    yellow = true, orange = true, purple = true,
    -- Add more if needed
  }

-- Set of known emphasis class names (optional, for validation)
local emphasis_classes = {
  emphasis = true, -- Or a more specific name like 'emphasize'
  -- Add more emphasis styles if needed
}

function Span(span)
  local color = span.attributes["color"]

  -- Fallback: check for known class names like .yellow
  if not color then
    for _, class in ipairs(span.classes) do
      if color_classes[class] then
        color = class
        break
      end
    end
  end

  -- If color found, apply it
  if color then
    local content = pandoc.utils.stringify(span.content)
    local format = FORMAT:lower()
    if format == 'html' then
      return pandoc.RawInline('html', '<span style="color:' .. color .. ';">' .. content .. '</span>')
    elseif format == 'latex' then
      return pandoc.RawInline('tex', '\\textcolor{' .. color .. '}{' .. content .. '}')
    else
      return span
    end
  end

  local emphasize = false
  -- Check for a specific attribute, e.g., 'emphasize'
  if span.attributes["emphasize"] == "true" then
    emphasize = true
  end

  -- Fallback: check for a known class name
  for _, class in ipairs(span.classes) do
    if emphasis_classes[class] then
      emphasize = true
      break
    end
  end

  -- If emphasis is requested, apply the class
  if emphasize then
    local content = pandoc.utils.stringify(span.content)
    local format = FORMAT:lower()
    if format == 'html' then
      return pandoc.RawInline('html', '<span class="emphasis">' .. content .. '</span>')
    elseif format == 'latex' then
      -- For LaTeX, you might still want a specific color command
      return pandoc.RawInline('tex', '\\textcolor{yellow}{' .. content .. '}') -- Or a custom command
    else
      return span
    end
  end

  return span
end
