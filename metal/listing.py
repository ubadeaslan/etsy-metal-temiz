"""Listing text: the text model sees the design image and writes from the product facts.

The description has one fixed layout: the model writes only the parts about this design (intro, style,
colors, inspiration, rooms, gift); the facts, the exact sizes, the questions and thank-you blocks and the
sign-off are put in by code, so no section goes missing and no fact is the model's own."""
from __future__ import annotations

import json
import re

from . import providers
from .mockup import FINISHES
from .sizes import CM, fmt_in

# Appended when AI was used (editable in the panel).
AI_DISCLOSURE = "Some elements of this item were created with the help of AI tools."

PRODUCT_EN = {
    "saat": "metal wall clock",
    "duvar": "metal wall art",
    "tabela": "personalized metal family name sign",
    "serbest": "metal wall decor",
    "portre": "custom metal portrait from the buyer's photo, with a name plate",
}
PERSONALIZED = {"tabela", "portre"}

HEART = {"Black": "🖤", "White": "🤍", "Silver": "🩶", "Bronze": "🤎", "Gold": "💛"}
# a finish the model wrote nothing for gets this line
COLOR_FALLBACK = {
    "Black": "Bold, timeless, and versatile. Perfect for rustic cabins, modern farmhouses, and minimalist interiors.",
    "White": "Clean, elegant, and sophisticated. Beautiful against dark or colorful walls.",
    "Silver": "Modern, sleek, and contemporary. Adds a refined metallic touch to your space.",
    "Bronze": "Warm, earthy, and rustic. A beautiful choice for wooden interiors and cozy spaces.",
    "Gold": "Luxurious, elegant, and eye-catching. Adds a sophisticated accent to any decor.",
}
QUESTIONS = (
    "We want you to find the perfect piece for your home!",
    "If you have any questions about sizes, colors, or customization possibilities, please feel free to contact "
    "us through Etsy messages.",
    "We're always happy to help you choose the right wall decor for your space.",
    "Please note: Colors may appear slightly different depending on your screen settings and room lighting.",
)

SYSTEM = """You write Etsy listings for a shop that sells CNC-cut metal wall decor (wall art, wall clocks,
family name signs) to buyers in the United States. Write natural, warm US English.

HARD RULES
- Use ONLY the product facts provided. Never invent materials, thickness, coatings, hardware, included
  parts, processing or shipping times, guarantees or care claims. If a fact is missing, do not mention it.
- Describe what is actually visible in the attached design image (motif, style, outline). Do not claim
  details you cannot see.
- Only a "metal wall clock" is a clock: for anything else never mention a clock, clock face or hands.
- No claims such as bestseller, best seller, #1, guaranteed, guarantee, top-rated, premium quality.
- Plain text everywhere: no markdown (no **, no #, no _).

TITLE: Title Case, 60-110 characters, under 15 words. Start with the strongest search phrase (the first target
search phrase if given, else what the item is, e.g. "Abstract Metal Wall Clock"), then " | " and a second
descriptive phrase a buyer would also search (motif + size or room). The characters % : & + may each
appear at most once. No keyword lists.

TAGS: exactly 13. Each at most 20 characters, lowercase, only letters, numbers and spaces. Multi-word
phrases buyers really type into Etsy search.
- Every target search phrase that fits in 20 characters is used as a tag, verbatim.
- At least 7 tags name the product itself (e.g. "metal wall clock", "large wall clock", "wave wall clock",
  "metal wall art", "family name sign").
- The rest cover motif, style, room, gift occasion and recipient (e.g. "housewarming gift").
- Never vague fragments such as "modern design", "metal art", "steel piece", "powder coated" or a bare color.
- No duplicates and no two tags with the same root phrase.

COPY: the parts of the description that are about THIS design. The code adds the facts, the size list,
the questions and thank-you blocks around them, so never write sizes, numbers of sizes or colors,
materials, care, shipping or the shop's contact text here. Match the STYLE EXAMPLE below in warmth,
rhythm and length (it is a listing for another design: take its tone, never its words or its motif).
Every field speaks about this design's motif, its mood, the interiors and the people
it suits; nothing generic.
- name_line: Title Case: the design as a buyer would name it, ending with what it is (e.g. "School of
  Fish Metal Wall Art", "Mountain Landscape Metal Wall Clock"), " – ", a short tagline.
- hook: one short excited line with one or two emoji that fit the motif.
- intro: 3 short paragraphs (1-2 sentences each): what the piece is (the main search phrase used
  naturally), what the design shows, the effect on the wall and the interiors it suits.
- design, style, shape, placement: short values for the feature list (style: 4-6 styles; placement:
  5-7 rooms, comma separated).
- sizes: 2 short paragraphs on choosing a size for this design: a smaller accent or a large statement
  piece, and the walls the larger sizes suit. No numbers. When sizes_offered is 1 there is no choice:
  describe how this one size reads on a wall and the walls and furniture it suits.
- colors_intro, colors_outro: one line each, about this design.
- colors: one entry per given finish, keyed by its name: two short sentences on how that color looks on
  this design and the interiors it suits.
- inspiration_heading: ALL CAPS, starting with one emoji that fits the motif.
- inspiration_subheading: a short line. inspiration: 3 short paragraphs on what the motif stands for and
  how the open-cut metal silhouette lets the wall color show through and casts soft shadows.
  inspiration_closing: one line on who will love it.
- spaces_intro: one line. styles: 5-7 interior styles that fit. rooms: 4-5 items {"room", "text"}.
- gift_for: ALL CAPS, the people this motif suits (e.g. NATURE LOVERS). gift_intro: one or two sentences
  ending with "makes a wonderful present for:". gift_items: 6-9 occasions and recipients.
  gift_closing: one line.
- thanks_line: one sentence on the shop's love of metal craft and designs like this one ("Inspired by
  ..., our goal is to bring ... into your favorite spaces.").

Return JSON only:
{"title": str, "tags": [13 strings], "materials": [up to 5 strings],
 "alt_text": str (at most 250 characters, describes the main photo),
 "copy": {"name_line": str, "hook": str, "intro": [str], "design": str, "style": str, "shape": str,
          "placement": str, "sizes": [str], "colors_intro": str, "colors": {finish name: str},
          "colors_outro": str, "inspiration_heading": str, "inspiration_subheading": str,
          "inspiration": [str], "inspiration_closing": str, "spaces_intro": str, "styles": [str],
          "rooms": [{"room": str, "text": str}], "gift_for": str, "gift_intro": str, "gift_items": [str],
          "gift_closing": str, "thanks_line": str}}

STYLE EXAMPLE (the description the code builds from such a copy):

"""

# The neutral example. A shop's own one (Ayarlar -> Açıklama stili örneği) takes its place.
STYLE_EXAMPLE = """Olive Branch Metal Wall Art – Botanical Wall Decor

Let a Quiet Garden Grow on Your Wall! 🌿

Bring calm, natural lines indoors with our Olive Branch Metal Wall Art, a cut-metal silhouette made for rooms that feel light and unhurried.

Long curving stems carry pairs of slender leaves and small round olives, arranged with open space between them so the whole piece stays airy.

In a sunlit kitchen, a linen-toned bedroom or a simple hallway, it adds movement to a bare wall without filling it.

With 5 beautiful color options and sizes from 20 in to 40 in wide (51 cm to 102 cm), you can choose the perfect combination for your space.

✨ PRODUCT FEATURES

• Design: Olive Branches with Leaves and Fruit
• Production: CNC Metal Cutting
• Style: Botanical, Mediterranean, Modern, Minimalist, Farmhouse
• Shape: Flowing Branch Silhouette
• Available Sizes: 20 in to 40 in wide (51 cm to 102 cm)
• Available Colors: Black, Gold, Silver, Bronze, White
• Placement: Kitchen, Dining Room, Living Room, Bedroom, Entryway, Office

📏 AVAILABLE SIZES

A smaller branch settles easily between two windows or above a narrow console, where a wall needs just one good line.

The larger sizes stretch comfortably over a sofa, a headboard or a long dining table.

Exact sizes (width × height):
• 20 × 13 in (51 × 33 cm)
• 40 × 26 in (102 × 66 cm)

🎨 CHOOSE YOUR FAVORITE COLOR

Each finish gives the branches a different season!

🖤 Black – Crisp as an ink drawing. A clear outline on pale plaster, white paint and light wood.

💛 Gold – Soft evening light on every leaf. Lovely on deep green, navy and warm neutral walls.

Whichever you pick, the leaves keep their fine, open outline.

🌿 INSPIRED BY THE OLIVE GROVE

Where Simple Lines Tell an Old Story

The olive branch has long stood for peace, patience and a generous table.

Its leaves are drawn here as clean shapes, close enough to feel full and open enough to breathe.

The open-cut metal silhouette lets your wall color show between the leaves and casts soft shadows as the day moves on.

Made for anyone who likes their home calm, green and a little sun-warmed.

🏡 PERFECT FOR YOUR SPACE

Our Olive Branch Metal Wall Art sits well with many interiors:

• Mediterranean & Coastal
• Modern & Minimalist
• Farmhouse & Cottage
• Scandinavian & Japandi

Kitchen: Hang it over open counters for a fresh, herb-garden mood.

Bedroom: Let the long stems follow the width of your headboard.

Entryway: Offer guests a quiet, welcoming first view.

🎁 A THOUGHTFUL GIFT FOR PLANT LOVERS

Looking for something lasting and easy to love? Our Olive Branch Metal Wall Art makes a wonderful present for:

• Housewarming parties
• Weddings and anniversaries
• Home cooks and gardeners

A piece of the garden that asks for no water and stays in leaf all year.

(... care, questions, thank-you and sign-off blocks are added by the code ...)"""


def system_prompt(style_example: str = "") -> str:
    return SYSTEM + (style_example.strip() or STYLE_EXAMPLE)


def size_range(widths: list[float]) -> str:
    """The width span in both units, e.g. '30 in to 79 in wide (76 cm to 201 cm)'."""
    ws = sorted(widths)
    if not ws:
        return ""
    lo, hi = ws[0], ws[-1]
    if lo == hi:
        return f"{fmt_in(lo)} in wide ({lo * CM:.0f} cm)"
    return f"{fmt_in(lo)} in to {fmt_in(hi)} in wide ({lo * CM:.0f} cm to {hi * CM:.0f} cm)"


def _facts_for(product_type: str, facts: dict) -> dict:
    """The facts that apply to this product (clock facts only for clocks, personalization only for signs)."""
    out = {k: v for k, v in facts.items() if k not in ("confirmed",) and v not in ("", None, False)}
    if product_type != "saat":
        out.pop("clock_movement", None)
        out.pop("clock_hands_included", None)
    if product_type not in PERSONALIZED:
        out.pop("personalization", None)
    return out


def user_message(record: dict, facts: dict, finishes: list[str], keywords: str, sizes_offered: int = 0) -> str:
    payload = {
        "product": PRODUCT_EN.get(record["product_type"], "metal wall decor"),
        "design_name": record.get("name", ""),
        "designer_notes": record.get("brief", ""),
        "finishes": [FINISHES[f]["label"] for f in finishes if f in FINISHES],
        "sizes_offered": sizes_offered,
        "facts": _facts_for(record["product_type"], facts),
        "target_search_phrases": keywords.strip(),
    }
    return ("Write the Etsy listing for this design. The attached image is the cut design "
            "(black = metal). Designer notes may be in Turkish: use their meaning, write English.\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2))


def plain_text(text: str) -> str:
    """Etsy descriptions are plain text: markdown the model slips in (**bold**, # headings) would show as
    symbols, so it goes; three or more line breaks become one empty line."""
    text = str(text or "").strip().replace("\r\n", "\n")
    text = re.sub(r"\*\*|__", "", text)
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _one(value) -> str:
    return re.sub(r"\s+", " ", plain_text(value)).strip()


def _many(value) -> list[str]:
    items = value if isinstance(value, list) else [value] if value else []
    return [s for s in (_one(v) for v in items) if s]


def build_description(copy: dict, product_type: str, facts: dict, sizes: list[str], widths: list[float],
                      finishes: list[str], shop: dict | None, ai_used: bool) -> str:
    """The description in the fixed layout: the model's copy about the design, the facts and blocks by code."""
    c = copy or {}
    facts = _facts_for(product_type, facts)
    shop = shop or {}
    name = _one(shop.get("name"))
    labels = [FINISHES[f]["label"] for f in finishes if f in FINISHES]
    span = size_range(widths)
    blocks: list[str] = []

    def add(*parts: str) -> None:
        blocks.extend(p for p in parts if p)

    def section(heading: str, *parts: str) -> None:
        body = [p for p in parts if p]
        if body:
            add(heading, *body)

    def bullets(items: list[str]) -> str:
        return "\n".join(f"• {i}" for i in items)

    add(_one(c.get("name_line")), _one(c.get("hook")), *_many(c.get("intro")))
    if span and len(set(widths)) > 1:
        add(f"With {len(labels)} beautiful color options and sizes from {span}, you can choose the perfect "
            "combination for your space.")
    elif span:
        add(f"With {len(labels)} beautiful color options in one size, {span}, you can choose the perfect "
            "finish for your space.")

    material = facts.get("material", "")
    if material and facts.get("thickness_mm"):
        material = f"{facts['thickness_mm']:g} mm {material}"
    if material and facts.get("coating"):
        material = f"{material}, {facts['coating']}"
    clock = facts.get("clock_movement", "")
    if facts.get("clock_hands_included"):
        clock = f"{clock}; clock hands included" if clock else "Clock hands included"
    features = [
        ("Design", _one(c.get("design"))), ("Material", material), ("Production", "CNC Metal Cutting"),
        ("Style", _one(c.get("style"))), ("Shape", _one(c.get("shape"))), ("Available Sizes", span),
        ("Available Colors", ", ".join(labels)),
        ("Function", "Decorative Wall Clock & Metal Wall Art" if product_type == "saat" else ""),
        ("Clock", clock), ("Mounting", facts.get("mounting", "")),
        ("Use", str(facts.get("indoor_outdoor", "")).capitalize()),
        ("Processing time", facts.get("processing_time", "")), ("Placement", _one(c.get("placement"))),
    ]
    section("✨ PRODUCT FEATURES", bullets([f"{k}: {v}" for k, v in features if v]))

    exact = "Exact sizes (width × height):\n" + bullets(sizes) if sizes else ""
    section("📏 AVAILABLE SIZES", *_many(c.get("sizes")), exact)

    notes = c.get("colors") if isinstance(c.get("colors"), dict) else {}
    lines = [f"{HEART.get(lb, '•')} {lb} – {_one(notes.get(lb)) or COLOR_FALLBACK.get(lb, '')}".rstrip(" –")
             for lb in labels]
    section("🎨 CHOOSE YOUR FAVORITE COLOR", _one(c.get("colors_intro")), *lines, _one(c.get("colors_outro")))

    heading = _one(c.get("inspiration_heading")).upper() or "✨ THE STORY BEHIND THE DESIGN"
    section(heading, _one(c.get("inspiration_subheading")), *_many(c.get("inspiration")),
            _one(c.get("inspiration_closing")))

    rooms = []
    for item in c.get("rooms") or []:
        if isinstance(item, dict) and _one(item.get("room")) and _one(item.get("text")):
            rooms.append(f"{_one(item['room'])}: {_one(item['text'])}")
    styles = _many(c.get("styles"))
    section("🏡 PERFECT FOR YOUR SPACE", _one(c.get("spaces_intro")), bullets(styles) if styles else "", *rooms)

    gift_items = _many(c.get("gift_items"))
    gift_for = _one(c.get("gift_for")).upper()
    section(f"🎁 A THOUGHTFUL GIFT FOR {gift_for}" if gift_for else "🎁 A THOUGHTFUL GIFT",
            _one(c.get("gift_intro")), bullets(gift_items) if gift_items else "", _one(c.get("gift_closing")))

    section("✏️ PERSONALIZATION", facts.get("personalization", ""))
    section("🧽 CARE", facts.get("care", ""))
    section("💌 QUESTIONS OR SPECIAL REQUESTS?", *QUESTIONS)
    thanks = _one(c.get("thanks_line"))
    section(f"❤️ THANK YOU FOR SUPPORTING {name.upper()}!" if name else "❤️ THANK YOU FOR VISITING OUR SHOP!",
            _one(shop.get("story")), thanks, "Thank you for visiting our shop and supporting our creative journey.",
            _one(shop.get("slogan")), f"— {name}" if name else "")
    if ai_used:
        add(AI_DISCLOSURE)
    return "\n\n".join(blocks)


def normalize(data: dict, ai_used: bool) -> dict:
    title = re.sub(r"\s+", " ", str(data.get("title", ""))).strip()
    seen, tags = set(), []
    for tag in data.get("tags", []) or []:
        clean = re.sub(r"\s+", " ", str(tag).lower()).strip()
        if clean and clean not in seen:
            seen.add(clean)
            tags.append(clean)
    description = plain_text(str(data.get("description", "")))
    if ai_used and AI_DISCLOSURE not in description:
        description = f"{description}\n\n{AI_DISCLOSURE}".strip()
    return {
        "title": title,
        "tags": tags[:13],
        "description": description,
        "materials": [str(m).strip() for m in (data.get("materials") or []) if str(m).strip()][:5],
        "alt_text": str(data.get("alt_text", "")).strip()[:250],
    }


def generate(record: dict, image_png: bytes, provider: str, facts: dict, sizes: list[str],
             finishes: list[str], keywords: str = "", shop: dict | None = None,
             widths: list[float] | None = None, style_example: str = "") -> tuple[dict, dict]:
    data, info = providers.generate_json(
        provider, system_prompt(style_example), user_message(record, facts, finishes, keywords, len(set(widths or []))),
        image_png=image_png, design_id=record["id"],
    )
    ai_used = record.get("ai_used", False)
    if isinstance(data.get("copy"), dict):
        data["description"] = build_description(data["copy"], record["product_type"], facts, sizes, widths or [],
                                                finishes, shop, ai_used)
    return normalize(data, ai_used), info
