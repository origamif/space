-- Image filter: add srcset, lazy loading for local assets.
-- Pandoc Lua filter for the Space blog build pipeline.
--
-- For local images (starting with /assets/), adds:
--   - srcset with 1x and 2x descriptors (@2x filename suffix convention)
--   - sizes for responsive layout
--   - lazy loading and async decoding
--
-- Pandoc already wraps captioned images in <figure>/<figcaption>,
-- so no explicit figure wrapping is needed here.

function Image(el)
  local src = el.src

  -- Only process local assets, not external URLs
  if src:sub(1, 8) ~= "/assets/" then
    return el
  end

  -- Extract filename and extension for srcset generation
  local base, ext = src:match("^(.+)%.(%w+)$")
  if not base then
    return el
  end
  local src_2x = base .. "@2x." .. ext

  -- Build srcset: always include 1x, optimistically include 2x
  el.attributes["srcset"] = src .. " 1x, " .. src_2x .. " 2x"
  el.attributes["sizes"] = "(max-width: 720px) 100vw, 720px"
  el.attributes["loading"] = "lazy"
  el.attributes["decoding"] = "async"

  return el
end
