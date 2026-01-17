function Div(el)
  if el.classes:includes("hintbox") then
    local openTag = pandoc.RawBlock("html", '<div class="hintFrame"><div class="hintInnerFrame">')
    local closeTag = pandoc.RawBlock("html", '</div></div>')

    local content = el.content or {}  -- Prevent nil errors
    local result = {openTag}

    for _, item in ipairs(content) do
      table.insert(result, item)
    end

    table.insert(result, closeTag)
    return result
  end


  if el.classes:includes("notebox") then
    local openTag = pandoc.RawBlock("html", '<div class="note"><div class="title">⚠ Note</div><div class="note content">')
    local closeTag = pandoc.RawBlock("html", '</div></div>')

    local content = el.content or {}  -- Prevent nil errors
    local result = {openTag}

    for _, item in ipairs(content) do
      table.insert(result, item)
    end

    table.insert(result, closeTag)
    return result
  end

end
