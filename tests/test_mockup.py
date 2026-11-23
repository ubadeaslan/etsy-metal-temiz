import numpy as np

from metal import config, mockup


def _disk(n: int = 300) -> np.ndarray:
    yy, xx = np.ogrid[:n, :n]
    return (yy - n / 2) ** 2 + (xx - n / 2) ** 2 <= (n * 0.45) ** 2


def test_palette_order_slots_and_no_matte():
    assert mockup.PALETTE == ("black", "gold", "silver", "bronze", "white")
    assert mockup.SLOTS == {"black": 2, "gold": 2, "silver": 1, "bronze": 1, "white": 1}
    assert mockup.FINISHES["black"]["label"] == "Black"
    assert all(f["metallic"] > 0 for f in mockup.FINISHES.values())


def test_size_rows_balance():
    assert [len(r) for r in mockup._size_rows(list(range(1, 11)))] == [5, 5]
    assert [len(r) for r in mockup._size_rows(list(range(1, 8)))] == [4, 3]
    assert [len(r) for r in mockup._size_rows([16, 20, 24])] == [3]


def test_cards_are_square():
    mask = _disk()
    assert mockup.CANVAS == (3000, 3000)
    assert mockup.size_card(mask, [12, 14, 16, 18, 20, 24, 28, 30, 32, 36]).size == mockup.CANVAS
    facts = config.load_settings()["facts"]
    assert mockup.info_card(mask, "black", facts, "saat", [16, 24]).size == mockup.CANVAS


def test_details_card_rows():
    facts = {"material": "steel", "thickness_mm": 1.5, "care": "Wipe."}
    rows = dict(mockup.info_rows(facts, "saat", [24, 16, 20]))
    assert rows["Material"] == "1.5 mm steel"
    assert rows["Sizes"] == '3 sizes, 16"–24" wide (41–61 cm)'  # a range in both units, not the full list
    assert dict(mockup.info_rows(facts, "saat", [30]))["Sizes"] == '30" wide (76 cm)'
    for spec in (mockup.DETAILS_TITLE, mockup.DETAILS_KEY, mockup.DETAILS_VALUE):  # the fonts ship with the panel
        assert (config.FONTS / spec[0]).exists()


def test_parse_sizes():
    assert config.parse_sizes(["24", "16", "x"], "38; 12.5, 16 0 500") == [12.5, 16, 24, 38]


def test_size_labels_agree_in_both_units():
    from metal import sizes

    d = sizes.dims(30, 0.4133)
    assert (d["label_in"], d["label_cm"], d["variation"]) == ("30 × 12.4 in", "76 × 31 cm", '30"x12.4"/76x31cm')
    assert sizes.dims(29.92, None)["label_w"] == '29.9"'


def test_variations_are_solid_and_fit_etsy():
    from metal import sizes

    rows = [sizes.dims(cm / 2.54, 0.655)["variation"] for cm in range(50, 140, 10)]
    assert rows[0] == '19.7"x12.9"/50x33cm'
    assert rows[-1] == '51.2"x33.5"/130x85cm'
    assert all(" " not in r and len(r) <= 20 for r in rows)
    square = sizes.dims(47.2, 1.0)["variation"]  # 120 x 120 cm: the long form is 21 characters
    assert square == '47.2x47.2"/120x120cm'
    assert len(sizes.dims(110, 1.0)["variation"]) <= 20


def test_clock_hands_stay_inside_a_small_dial():
    """A clock inside a wide scene: the hands are sized from the dial's rim, not from the whole design."""
    import numpy as np

    from metal import compose, mockup

    h, w = 600, 1500
    yy, xx = np.ogrid[:h, :w]
    d = np.hypot(yy - (h - 1) / 2, xx - (w - 1) / 2)
    scene_mask = np.zeros((h, w), dtype=bool)
    scene_mask[400:] = True                                   # landscape
    scene_mask |= (d >= 150) & (d <= 170)                     # dial rim, inner radius 150 px
    scene_mask |= d <= 90                                     # solid centre
    scene_mask = compose.add_clock_hub(scene_mask, 1500, 0.12, 10)
    reach = mockup.dial_reach(scene_mask)
    assert abs(reach - 150 / 0.94 / 300) < 0.02
    main, second = mockup._clock_hands(w, h, round(reach, 3))
    for layer in (main, second):
        ys, xs = np.nonzero(layer > 0.5)
        assert np.hypot(ys - h / 2, xs - w / 2).max() < 150  # every hand ends inside the rim

    round_clock = np.hypot(*np.ogrid[-300:300, -300:300]) <= 299
    round_clock &= ~((np.hypot(*np.ogrid[-300:300, -300:300]) > 100) & (np.hypot(*np.ogrid[-300:300, -300:300]) < 281))
    assert mockup.dial_reach(compose.add_clock_hub(round_clock, 600, 0.12, 10)) == 1.0  # round clocks: as before

    # a geometric clock with inner circles: the outer rim is the dial, the inner rings are decoration
    rr = np.hypot(*np.ogrid[-300:300, -300:300])
    geometric = (rr <= 70) | ((rr >= 115) & (rr <= 125)) | ((rr >= 185) & (rr <= 197)) | ((rr >= 281) & (rr <= 299))
    geometric |= (np.abs(np.ogrid[-300:300, -300:300][1]) <= 8) & (rr <= 299)  # spokes holding the rings
    assert mockup.dial_reach(compose.add_clock_hub(geometric, 600, 0.12, 10)) == 1.0


def test_size_guide_clocks_have_gold_hands():
    import numpy as np

    from metal import compose, mockup, raster
    from tests import ornek

    mask = compose.add_clock_hub(raster.prepare(ornek.clock_face(800)), 400, 0.12, 10)
    gold = mockup._hex(mockup.FINISHES["gold"]["tones"][1])
    for clock, expect in ((True, True), (False, False)):
        tile = np.asarray(mockup._flat_design(mask, 600, (40, 40, 42), "gold" if clock else None))
        solid = tile[..., 3] > 250
        near_gold = (np.abs(tile[..., :3].astype(float) - gold).sum(axis=-1) < 30) & solid
        assert near_gold.any() == expect
    card = mockup.size_card(mask, [16, 24], clock=True)
    assert card.size == mockup.CANVAS
