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
    local openTag = pandoc.RawBlock("html", '<div class="note"><div class="note-title">⚠ Note</div><div class="note-body">')
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

-- Headings that open a worked example ("## Example 3: ...", "### Exempel 2") get the class
-- example, which Quarto carries to the enclosing <section>, so custom.scss can mark the whole
-- example however its id was set.
function Header(el)
  local text = pandoc.utils.stringify(el.content)
  if (text:match("^Example") or text:match("^Exempel")) and not el.classes:includes("example") then
    el.classes:insert("example")
  end
  return el
end
