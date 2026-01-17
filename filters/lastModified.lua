local function get_last_modified_date(filepath)
    -- Adjust command based on OS
    local command
    if package.config:sub(1,1) == "\\" then
      -- Windows
      command = string.format('for %%A in ("%s") do @echo %%~tA', filepath)
    else
      -- Linux/macOS
      command = string.format("stat -c %%y %s", filepath)
    end

    local handle = io.popen(command, "r")
    local result = handle:read("*a")
    handle:close()

    if result then
      return result:match("(%d%d%d%d%-%d%d%-%d%d)") or "Unknown"
    else
      return "Unknown"
    end
  end

  return {
    {
      Pandoc = function(doc)
        -- Get the last modified date
        local last_modified = get_last_modified_date(quarto.doc.input_file)

        -- Inject the date into the body as a raw inline
        table.insert(doc.blocks, pandoc.RawBlock("html", string.format([[
          <script>
            document.addEventListener("DOMContentLoaded", function() {
              document.getElementById("last-modified").textContent = "%s";
            });
          </script>
        ]], last_modified)))

        return doc
      end
    }
  }
