-- llms-math.lua
-- MathJax output keeps its TeX in <span class="math inline">\(..\)</span> and
-- <span class="math display">\[..\]</span>. Pandoc's HTML reader leaves that as plain
-- text, which the markdown writer then escapes beyond recognition, so the span is turned
-- back into a Math element. Used by quarto_shared/llms.py.
function Span(el)
  if not el.classes:includes("math") then return nil end
  local tex = pandoc.utils.stringify(el)
  if el.classes:includes("display") then
    tex = tex:gsub("^%s*\\%[", ""):gsub("\\%]%s*$", "")
    return pandoc.Math("DisplayMath", tex)
  end
  tex = tex:gsub("^%s*\\%(", ""):gsub("\\%)%s*$", "")
  return pandoc.Math("InlineMath", tex)
end
