-- penmentor sends this plugin's shortcut when you ask a question; the plugin exports the current page as a PNG
-- (from memory, so unsaved strokes count) to ~/.cache/penmentor/page.png, plus "page pages" in page.txt.

function initUi()
  app.registerUi({menu = "penmentor: share the current page", callback = "penmentorSharePage", accelerator = "<Control><Alt><Shift>F12"})
end

function penmentorSharePage()
  local dir = (os.getenv("XDG_CACHE_HOME") or (os.getenv("HOME") .. "/.cache")) .. "/penmentor"
  local doc = app.getDocumentStructure()
  app.export({outputFile = dir .. "/page.tmp.png", range = tostring(doc.currentPage), background = "all", pngDpi = 150})
  local f = io.open(dir .. "/page.tmp.txt", "w")
  if f then
    f:write(doc.currentPage, " ", #doc.pages)
    f:close()
    os.rename(dir .. "/page.tmp.txt", dir .. "/page.txt")
  end
  os.rename(dir .. "/page.tmp.png", dir .. "/page.png")  -- last: penmentor waits for this file
end
