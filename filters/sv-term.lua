-- Swedish terms: [pitch circle]{sv="delningscirkel"}
--
-- The English term stays in the sentence. In HTML it gets its own colour and a dotted
-- underline, and hovering over it, or tapping it (tabindex makes it focusable), shows the
-- Swedish term in a small box. In LaTeX and every other format the Swedish term follows
-- in brackets: pitch circle (sv. delningscirkel).
function Span(span)
  local sv = span.attributes["sv"]
  if not sv then
    return nil
  end
  span.attributes["sv"] = nil
  if FORMAT:match("html") then
    span.classes:insert("sv-term")
    span.attributes["tabindex"] = "0"
    span.attributes["lang"] = "en"
    local tip = pandoc.Span({pandoc.Str("sv."), pandoc.Space(), pandoc.Emph(pandoc.Str(sv))},
                            {class = "sv-tip", role = "tooltip", lang = "sv"})
    span.content:insert(tip)
    return span
  end
  local after = {pandoc.Space(), pandoc.Str("(sv."), pandoc.Space(), pandoc.Emph(pandoc.Str(sv)),
                 pandoc.Str(")")}
  local out = span.content
  for _, el in ipairs(after) do
    out:insert(el)
  end
  return out
end
