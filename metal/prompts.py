"""CNC prompt templates per product type."""
from __future__ import annotations

ASPECTS = {"saat": "1:1", "duvar": "3:2", "tabela": "3:2", "serbest": "1:1", "portre": "4:5"}

BASE_RULES = """You are designing production artwork for CNC plasma / laser cut sheet-metal wall decor.
STRICT RENDERING RULES (the image is traced directly into a cutting path):
- Exactly two colors: solid pure black (#000000) shapes on a pure white (#FFFFFF) background.
- Flat 2D stencil silhouette. No gradients, no gray, no shading, no texture, no 3D, no perspective, no photo, no drop shadow.
- Black = metal that remains, white = cut away. ALL black areas must join into ONE single continuous piece:
  nothing may float. Join the parts through the artwork itself: shapes that touch or overlap, shared outlines,
  short bridges between neighbouring shapes.
- Do NOT add a frame, border, ring, outline around the design, base bar or ground line unless the brief asks
  for one. The outer shape of the piece is the outline of the artwork itself.
- Bold, chunky shapes. No hairlines: the thinnest black part is at least 1% of the image width,
  every white gap is at least 0.7% of the image width. Avoid tiny dots and tiny holes.
- The whole design is fully visible and centered with about 6% white margin on every side; nothing touches the image edge.
- No watermark, no signature, no mockup, no wall, no frame around the picture itself."""

TYPE_RULES = {
    "saat": """PRODUCT: a decorative wall clock face cut from one metal sheet.
- Overall composition is circular (unless the brief asks for another outline) and centered in the square image.
- Keep a SOLID black disk in the exact center, about 12% of the design diameter, with nothing cut out of it:
  the clock movement mounts behind it.
- Mark the 12 hour positions with bold markers or numerals that are part of the connected metal,
  unless the brief says no markers.
- Do NOT draw clock hands.""",
    "duvar": """PRODUCT: a decorative metal wall art panel / silhouette scene.
- A wide landscape composition that reads well from across a room.
- In a scene with many separate elements, let them overlap or touch one another so every element connects.""",
    "tabela": """PRODUCT: a personalized family name / house sign.
- Include the sample text "{sample}" in a bold, highly legible, stencil-friendly typeface.
- Every letter is black metal that touches the artwork or a solid base bar so no letter floats.
- Letter holes (inside O, A, B, D, P, R, e, a...) are cut-outs in black metal: keep them, they do not float.
- Decorative artwork around the text follows the brief.""",
    "serbest": """PRODUCT: decorative metal wall decor following the brief exactly.""",
}

SAMPLE_TEXT = "The Johnsons"


def build_prompt(product_type: str, brief: str, sample_text: str = "") -> str:
    rules = TYPE_RULES.get(product_type, TYPE_RULES["serbest"]).format(sample=sample_text or SAMPLE_TEXT)
    no_text = "" if product_type == "tabela" else "\n- No text, letters or numbers unless the brief explicitly asks for them (hour numerals on clocks are allowed)."
    return f"{BASE_RULES}{no_text}\n\n{rules}\n\nBRIEF FROM THE DESIGNER:\n{brief.strip()}"



# --- custom portrait from a photo (filled style; the name plate is added by code) -----------------------

PORTRAIT_ASPECTS = {"dikey": "4:5", "kare": "1:1", "yatay": "4:3"}

PORTRAIT = """Turn the subject of this photo into a bold FILLED stencil portrait for metal wall art: the subject
is a mostly solid black silhouette, with the facial features, fur or hair flow and the main details carved out
as white shapes, like a classic laser-cut metal stencil. Strong, simple, readable from across a room.

It will be cut from ONE sheet of 1.5 mm steel on a CNC plasma/laser cutter and hung on a wall, so:
- Pure black (#000000) shapes on a pure white (#FFFFFF) background only: no grey, no gradients, no shading,
  no texture, no text or letters, no frame, no scenery or background objects (leave out everything around
  the subject: furniture, plants, railings, bags).
- Every black part is connected into ONE single continuous piece: absolutely no floating islands. Eyes,
  pupils, eye highlights, nostrils, whiskers, hair strands, ears and clothing details touch or join the
  surrounding black shapes; if a detail would float, merge it into a neighbouring shape or leave it out.
- Add a straight horizontal black base bar along the bottom, as wide as the portrait, that the whole
  portrait stands on and connects to. Leave nothing below the bar: a name plate is added under it later.
- SIMPLIFY for metal: fur and hair as a few large bold locks, not fine strands; clothing patterns and prints
  as plain areas; no more than about 40 carved white shapes in total; no hairlines (every black line and
  bridge at least 1/120 of the image width) and no tiny pin holes.
- Keep the likeness faithful: face shape, eyes, expression, hair or fur pattern, how the subjects stand
  together. Centre the subject with a small white margin."""


def portrait_prompt(note: str = "") -> str:
    note = note.strip()
    return PORTRAIT + (f"\n\nNOTE FROM THE MAKER (may be Turkish): {note}" if note else "")
