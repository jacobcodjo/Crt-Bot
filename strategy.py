"""
Implémentation de la méthodologie Candle Range Trading (CRT) :

1. Range de référence = haut/bas de la dernière bougie D1 et/ou H4 clôturée.
2. Sweep de liquidité = une bougie (sur le TF de confirmation) dépasse ce range
   puis se referme à l'intérieur (piège / stop hunt).
3. Confirmation avancée = cassure de structure (MSS) dans le sens du retournement,
   accompagnée d'un Fair Value Gap (FVG) et/ou d'un Order Block (OB).

Cette logique est une implémentation simplifiée des concepts ICT / Smart Money
Concepts. Elle est fournie à titre d'outil d'aide à la décision, pas comme un
système de trading garanti — à affiner et backtester avant tout usage réel.
"""


def last_closed_candle(candles):
    """Retourne la dernière bougie considérée comme clôturée (avant-dernière de la liste,
    car la dernière renvoyée par l'API est généralement encore en formation)."""
    if len(candles) < 2:
        return None
    return candles[-2]


def get_reference_range(htf_candles):
    ref = last_closed_candle(htf_candles)
    if not ref:
        return None
    return {"high": ref["high"], "low": ref["low"], "epoch": ref["epoch"]}


def find_swing_highs_lows(candles, left=3, right=3):
    """Détection simple de swing points (pivots) sur une série de bougies."""
    highs, lows = [], []
    for i in range(left, len(candles) - right):
        window = candles[i - left:i + right + 1]
        if candles[i]["high"] == max(c["high"] for c in window):
            highs.append(i)
        if candles[i]["low"] == min(c["low"] for c in window):
            lows.append(i)
    return highs, lows


def detect_liquidity_sweep(ltf_candles, range_high, range_low, ref_epoch):
    """Cherche une bougie qui dépasse le range de référence puis se referme
    à l'intérieur (piège de liquidité / stop hunt)."""
    events = []
    for i, c in enumerate(ltf_candles):
        if c["epoch"] <= ref_epoch:
            continue
        if c["high"] > range_high and c["close"] < range_high:
            events.append({"index": i, "direction": "bearish", "candle": c})
        if c["low"] < range_low and c["close"] > range_low:
            events.append({"index": i, "direction": "bullish", "candle": c})
    return events


def detect_structure_shift(ltf_candles, sweep_index, direction, left=2, right=2):
    """Vérifie qu'après le sweep, le prix casse un swing récent dans le sens
    opposé au sweep (confirmation de retournement de structure)."""
    highs, lows = find_swing_highs_lows(ltf_candles[:sweep_index + 1], left, right)

    if direction == "bearish":
        if not lows:
            return None
        pivot_level = ltf_candles[lows[-1]]["low"]
        for j in range(sweep_index + 1, len(ltf_candles)):
            if ltf_candles[j]["close"] < pivot_level:
                return {"break_index": j, "level": pivot_level}
    else:
        if not highs:
            return None
        pivot_level = ltf_candles[highs[-1]]["high"]
        for j in range(sweep_index + 1, len(ltf_candles)):
            if ltf_candles[j]["close"] > pivot_level:
                return {"break_index": j, "level": pivot_level}
    return None


def detect_fvg(candles, around_index, direction, window=5):
    """Cherche un Fair Value Gap (déséquilibre 3 bougies) proche de l'index donné.
    Bullish FVG : high(bougie1) < low(bougie3). Bearish FVG : low(bougie1) > high(bougie3)."""
    start = max(1, around_index - window)
    end = min(len(candles) - 1, around_index + window)
    for i in range(start, end):
        if i + 1 >= len(candles):
            break
        c1, c3 = candles[i - 1], candles[i + 1]
        if direction == "bullish" and c1["high"] < c3["low"]:
            return {"index": i, "top": c3["low"], "bottom": c1["high"]}
        if direction == "bearish" and c1["low"] > c3["high"]:
            return {"index": i, "top": c1["low"], "bottom": c3["high"]}
    return None


def detect_order_block(candles, around_index, direction, window=5):
    """Cherche la dernière bougie opposée au mouvement (order block) avant l'impulsion.
    Bullish OB : dernière bougie baissière avant une impulsion haussière (et inversement)."""
    start = max(0, around_index - window)
    for i in range(around_index, start - 1, -1):
        c = candles[i]
        is_bearish = c["close"] < c["open"]
        is_bullish = c["close"] > c["open"]
        if direction == "bullish" and is_bearish:
            return {"index": i, "high": c["high"], "low": c["low"]}
        if direction == "bearish" and is_bullish:
            return {"index": i, "high": c["high"], "low": c["low"]}
    return None


def analyze_symbol(symbol, htf_candles_by_tf, ltf_candles):
    """Analyse un symbole sur les TF de référence fournis (D1, H4) et cherche
    un setup CRT confirmé (sweep + structure shift + FVG/OB) sur le TF de confirmation."""
    setups = []
    for tf_name, htf_candles in htf_candles_by_tf.items():
        ref_range = get_reference_range(htf_candles)
        if not ref_range:
            continue

        sweeps = detect_liquidity_sweep(
            ltf_candles, ref_range["high"], ref_range["low"], ref_range["epoch"]
        )

        for sweep in sweeps:
            structure = detect_structure_shift(ltf_candles, sweep["index"], sweep["direction"])
            if not structure:
                continue

            fvg = detect_fvg(ltf_candles, structure["break_index"], sweep["direction"])
            ob = detect_order_block(ltf_candles, sweep["index"], sweep["direction"])

            if not fvg and not ob:
                continue  # pas de confirmation avancée -> setup ignoré

            setups.append({
                "symbol": symbol,
                "reference_tf": tf_name,
                "ref_epoch": ref_range["epoch"],
                "direction": sweep["direction"],
                "range_high": ref_range["high"],
                "range_low": ref_range["low"],
                "sweep_candle": sweep["candle"],
                "structure_break_level": structure["level"],
                "fvg": fvg,
                "order_block": ob,
            })
    return setups
