# This is a deterministic safety net that doesn't depend on the AI
# classification call — even if that call fails or misses something, this
# plain keyword check still has a chance to flag a genuinely dangerous complaint.
def check_safety_flag(text: str) -> bool:
    normal_text = text.lower()

    # squished_text strips out spaces AND common punctuation, so a danger
    # word broken up by any of these — "g.as le-ak", "f,i,r,e" — still comes
    # back together into one contiguous word the substring checks can find.
    squished_text = normal_text
    for separator in [" ", ".", "-", ",", "_", "!", "?", ";", ":"]:
        squished_text = squished_text.replace(separator, "")

    # Standalone danger words: if any single variant shows up anywhere in
    # either text version, that's enough on its own to flag the complaint.
    standalone_words = {
        "fire": ["fire", "fyre", "fier", "fir"],
        "shock": ["shock", "shok", "shocked", "shoked"],
        "smoke": ["smoke", "smok", "somke"],
        "weapon": ["weapon", "weapn", "wepon"],
        "assault": ["assault", "asault", "assult"],
        "intruder": ["intruder", "intrudar", "intruderr"],
        "unconscious": ["unconscious", "unconcious"],
        "bleeding": ["bleeding", "bleading", "bleed", "bled"],
        "flooding": ["flooding", "flood", "floood", "flooing"],
        "collapse": ["collaps", "collapsed", "colapse", "colapsed"],
        "trapped": ["trap", "trapped", "traped", "trappd"],
        "electrocuted": ["electrocut", "electrocuted", "electrocution"],
        # Someone being hurt, or the writer calling it an emergency/danger, is
        # exactly the kind of complaint that must never rely on the AI alone.
        "injury": ["injur", "injurd", "hurt", "ambulance", "ambulence"],
        "emergency": ["emergency", "emergancy", "emergncy", "dangerous", "dangerus"],
    }

    # Short misspellings that are also fragments of ordinary words ("fir"
    # sits inside "first", "firm", "confirm") only count when they appear as
    # a whole word, otherwise "my flat is on the first floor" was flagged as
    # a fire. The spaced-out/punctuated check below isn't used for these.
    whole_word_only = ["fir"]
    words = "".join(ch if ch.isalnum() else " " for ch in normal_text).split()

    for variants in standalone_words.values():
        for variant in variants:
            if variant in whole_word_only:
                if variant in words:
                    return True
                continue
            if variant in normal_text or variant in squished_text:
                return True

    # Pair danger concepts: neither side alone is necessarily dangerous
    # (a stuck lift, or the word "gas" alone, isn't an emergency by
    # itself), but both sides together is a strong signal.
    pairs = [
        (["lift", "lyft", "lft"], ["stuck", "stuk", "stck"]),
        (["gas", "gaz", "gass"], ["leak", "leek", "leack", "smell", "smel"]),
        (["wire", "wires", "wyre"], ["spark", "sparking", "sparkin"]),
        (["live", "livs"], ["wire", "wires", "wyre"]),
    ]

    for side_a_variants, side_b_variants in pairs:
        side_a_found = False
        for variant in side_a_variants:
            if variant in normal_text or variant in squished_text:
                side_a_found = True
                break

        side_b_found = False
        for variant in side_b_variants:
            if variant in normal_text or variant in squished_text:
                side_b_found = True
                break

        if side_a_found and side_b_found:
            return True

    return False
