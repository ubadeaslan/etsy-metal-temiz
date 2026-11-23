from metal import preflight, prompts, store
from metal.listing import AI_DISCLOSURE, normalize


def test_prompt_carries_cnc_rules_and_type_rules():
    p = prompts.build_prompt("saat", "soyut dalgalar")
    assert "ONE single continuous piece" in p and "Do NOT draw clock hands" in p and "soyut dalgalar" in p
    assert "The Johnsons" in prompts.build_prompt("tabela", "dağlar")


def test_prompt_never_asks_for_a_frame_on_its_own():
    """A frame, border or base is added only when the brief asks for it."""
    for kind in ("duvar", "serbest", "saat"):
        p = prompts.build_prompt(kind, "abstract woman").lower()
        assert "do not add a frame" in p
        assert "border ring" not in p and "ground line or frame" not in p


def test_normalize_appends_disclosure_and_caps_tags():
    data = {"title": "  Metal  Wall Art ", "tags": [f"tag {i}" for i in range(16)] + ["tag 1"], "description": "Nice."}
    out = normalize(data, ai_used=True)
    assert out["title"] == "Metal Wall Art"
    assert len(out["tags"]) == 13
    assert out["description"].endswith(AI_DISCLOSURE)


def test_preflight_checks_format_and_claims_only():
    rec = store.create("duvar", "mountains", "Dağ")
    rec["ai_used"] = True
    rec["check"] = {"ok": False}
    rec["listing"] = {
        "title": "Mountain Metal Wall Art | Bestseller Harley-Davidson Decor",
        "tags": ["mountain wall art"] * 2,
        "description": "Silent quartz clock, see www.example.com",
    }
    found = {(f["level"], f["code"]) for f in preflight.check(rec)}
    assert ("HATA", "CLAIM-001") in found
    assert ("HATA", "META-002") in found  # duplicate tag
    codes = {code for _, code in found}
    assert not codes & {"IP-001", "LINK-001", "AI-001", "FACT-001", "FACT-002", "CUT-001"}, codes


def test_preflight_product_type_against_clock_in_title():
    rec = store.create("duvar", "fish", "Balık")
    rec["listing"] = {"title": "Metal Wall Clock | School of Fish Wall Decor", "tags": [], "description": ""}
    assert ("HATA", "TYPE-001") in {(f["level"], f["code"]) for f in preflight.check(rec)}
    rec["listing"]["title"] = "School of Fish Metal Wall Art | Ocean Decor"
    assert "TYPE-001" not in {f["code"] for f in preflight.check(rec)}
    rec["product_type"] = "saat"
    assert ("UYARI", "TYPE-001") in {(f["level"], f["code"]) for f in preflight.check(rec)}
    rec["listing"]["title"] = "Fish Wall Clocks | Ocean Decor"
    assert "TYPE-001" not in {f["code"] for f in preflight.check(rec)}


def test_description_built_in_the_fixed_layout():
    from metal.listing import build_description

    facts = {"material": "steel", "thickness_mm": 1.5, "coating": "powder coated", "mounting": "",
             "clock_movement": "Silent quartz movement", "personalization": "Type the name.", "care": "Wipe dry.",
             "indoor_outdoor": "indoor"}
    copy = {"name_line": "School of Fish Metal Wall Art – Ocean Silhouette", "hook": "Bring the sea home! 🐟",
            "intro": ["One.", "**Two.**"], "design": "Fish", "colors": {"Black": "Deep and bold."},
            "inspiration_heading": "🌊 inspired by the sea", "inspiration": ["Together."], "rooms": [{"room": "Bedroom", "text": "Calm."}],
            "gift_for": "ocean lovers", "gift_items": ["Housewarming"], "thanks_line": "We love the sea."}
    shop = {"name": "Demo Metal Shop", "slogan": "Metal for every wall.", "story": "At Demo, we cut with care."}
    sizes = ["30 × 9 in (76 × 23 cm)", "47.2 × 14 in (120 × 36 cm)"]
    text = build_description(copy, "duvar", facts, sizes, [30, 47.2], ["black", "gold"], shop, ai_used=True)
    for part in ("✨ PRODUCT FEATURES", "• Material: 1.5 mm steel, powder coated", "• Use: Indoor",
                 "📏 AVAILABLE SIZES\n\nExact sizes (width × height):\n• 30 × 9 in (76 × 23 cm)",
                 "sizes from 30 in to 47.2 in wide (76 cm to 120 cm)", "🖤 Black – Deep and bold.",
                 "💛 Gold – Luxurious", "🌊 INSPIRED BY THE SEA", "Bedroom: Calm.",
                 "🎁 A THOUGHTFUL GIFT FOR OCEAN LOVERS", "💌 QUESTIONS OR SPECIAL REQUESTS?",
                 "❤️ THANK YOU FOR SUPPORTING DEMO METAL SHOP!\n\nAt Demo, we cut with care.\n\nWe love the sea.",
                 "\n\nMetal for every wall.\n\n— Demo Metal Shop\n\n" + AI_DISCLOSURE):
        assert part in text, part
    assert text.startswith("School of Fish Metal Wall Art – Ocean Silhouette\n\nBring the sea home! 🐟\n\nOne.\n\nTwo.")
    assert text.endswith(AI_DISCLOSURE) and "**" not in text
    # not a clock, not personalized, no mounting fact: none of those lines
    assert "Clock" not in text and "PERSONALIZATION" not in text and "Mounting" not in text

    one = build_description({}, "saat", facts, sizes[:1], [30], ["black"], {}, ai_used=False)
    assert "in one size, 30 in wide (76 cm)" in one and "• Clock: Silent quartz movement" in one
    assert "• Function: Decorative Wall Clock & Metal Wall Art" in one
    assert "THANK YOU FOR VISITING OUR SHOP!" in one and AI_DISCLOSURE not in one
