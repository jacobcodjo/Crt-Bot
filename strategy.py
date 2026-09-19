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

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config import (
    STRICT_CONFIRMATION_TIMEFRAMES,
    STOP_LOSS_BUFFER_PCT,
    SYNTHETIC_INDEX_PREFIXES,
    SYNTHETIC_TP_EXTENSION_PCT,
    MIN_RISK_REWARD,
    REQUIRE_FIB_OTE,
    TREND_SWING_WINDOW,
    TREND_SWING_COUNT,
    TREND_SMA_PERIOD,
    TIMEFRAME_CASCADE,
    STRUCTURE_SWING_WINDOW,
    DEFAULT_STRUCTURE_SWING_WINDOW,
    ORDER_TYPE_TOLERANCE_PCT,
    KILLZONES_NY_TIME,
    REQUIRE_KILLZONE_FOR_REAL_MARKETS,
    GRANULARITY,
    WEEKEND_GAP_PREFIXES,
    WEEKEND_GAP_MULTIPLIER,
    LIQUIDITY_POOL_SWING_WINDOW,
    LIQUIDITY_POOL_TOLERANCE_PCT,
    STOP_LOSS_POOL_BUFFER_PCT,
)


def last_closed_candle(candles):
    """Retourne la dernière bougie considérée comme clôturée (avant-dernière de la liste,
    car la dernière renvoyée par l'API est généralement encore en formation)."""
    if len(candles) < 2:
        return None
    return candles[-2]


def get_reference_range(htf_candles):
    if not htf_candles:
        return None
    ref = last_closed_candle(htf_candles)
    if not ref:
        return None
    return {"high": ref["high"], "low": ref["low"], "epoch": ref["epoch"]}


def build_weekly_range(d1_candles):
    """
    Calcule le range W1 (haut/bas de la dernière semaine calendaire complète)
    en agrégeant des bougies D1 déjà récupérées — pas de requête API séparée,
    Deriv ne supportant pas de façon fiable une granularité hebdomadaire directe.
    """
    if not d1_candles or len(d1_candles) < 2:
        return None
    closed = d1_candles[:-1]  # exclut la bougie du jour en cours

    weeks = {}
    for c in closed:
        dt = datetime.fromtimestamp(c["epoch"], tz=timezone.utc)
        key = dt.isocalendar()[:2]  # (année ISO, numéro de semaine ISO)
        weeks.setdefault(key, []).append(c)

    if len(weeks) < 2:
        return None  # pas assez d'historique pour identifier une semaine complète

    # La dernière clé triée correspond à la semaine en cours (potentiellement
    # incomplète) -> on utilise l'avant-dernière, la dernière semaine complète.
    last_complete_key = sorted(weeks.keys())[-2]
    week_candles = weeks[last_complete_key]

    return {
        "high": max(c["high"] for c in week_candles),
        "low": min(c["low"] for c in week_candles),
        "epoch": week_candles[-1]["epoch"],
    }


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


def group_equal_levels(values, tolerance_pct=LIQUIDITY_POOL_TOLERANCE_PCT):
    """Regroupe des valeurs proches (écart relatif <= tolerance_pct) en niveaux ;
    ne retourne que les groupes d'au moins 2 valeurs (un seul pivot isolé n'est
    pas un pool de liquidité, il en faut au moins deux à peu près égaux)."""
    if not values:
        return []
    sorted_vals = sorted(values)
    groups = []
    current = [sorted_vals[0]]
    for v in sorted_vals[1:]:
        if abs(v - current[-1]) / current[-1] <= tolerance_pct:
            current.append(v)
        else:
            if len(current) >= 2:
                groups.append(sum(current) / len(current))
            current = [v]
    if len(current) >= 2:
        groups.append(sum(current) / len(current))
    return groups


def find_liquidity_pools(candles, swing_window=LIQUIDITY_POOL_SWING_WINDOW,
                          tolerance_pct=LIQUIDITY_POOL_TOLERANCE_PCT):
    """
    Détecte les pools de liquidité (Equal Highs / Equal Lows) : des sommets ou
    creux quasi identiques, signe que plusieurs traders ont probablement placé
    leurs stops au même niveau. Retourne (high_pools, low_pools), chacun une
    liste de niveaux de prix.
    """
    highs_idx, lows_idx = find_swing_highs_lows(candles, swing_window, swing_window)
    high_pools = group_equal_levels([candles[i]["high"] for i in highs_idx], tolerance_pct)
    low_pools = group_equal_levels([candles[i]["low"] for i in lows_idx], tolerance_pct)
    return high_pools, low_pools


def is_near_level(price, levels, tolerance_pct=LIQUIDITY_POOL_TOLERANCE_PCT):
    return any(abs(price - lvl) / lvl <= tolerance_pct for lvl in levels)


def has_weekend_gaps(symbol):
    """Forex et or ferment le marché le weekend -> sujets aux gaps. Cryptos et
    indices synthétiques tournent 24/7, jamais concernés."""
    return symbol.startswith(WEEKEND_GAP_PREFIXES)


def is_gap_candle(candles, index, granularity_seconds, gap_multiplier=WEEKEND_GAP_MULTIPLIER):
    """Une bougie est un 'gap' si l'écart avec la précédente dépasse largement la
    granularité normale -- signe d'une fermeture de marché (weekend), pas d'un
    vrai mouvement intrabar exploitable."""
    if index == 0 or not granularity_seconds:
        return True  # pas de bougie précédente pour comparer -> prudence
    return (candles[index]["epoch"] - candles[index - 1]["epoch"]) > granularity_seconds * gap_multiplier


def detect_liquidity_sweep(ltf_candles, range_high, range_low, ref_epoch,
                            granularity_seconds=None, check_gaps=False):
    """Cherche une bougie qui dépasse le range de référence puis se referme
    à l'intérieur (piège de liquidité / stop hunt). Si check_gaps est actif
    (forex/or), ignore les bougies qui suivent un gap de weekend."""
    events = []
    for i, c in enumerate(ltf_candles):
        if c["epoch"] <= ref_epoch:
            continue
        if check_gaps and is_gap_candle(ltf_candles, i, granularity_seconds):
            continue  # gap de weekend -> pas un vrai sweep, ignoré
        if c["high"] > range_high and c["close"] < range_high:
            events.append({"index": i, "direction": "bearish", "candle": c})
        if c["low"] < range_low and c["close"] > range_low:
            events.append({"index": i, "direction": "bullish", "candle": c})
    return events


def find_index_after_epoch(candles, epoch):
    """Retourne l'index de la première bougie dont l'epoch dépasse celui donné
    (utilisé pour passer d'un epoch détecté sur le MTF à un point de départ
    équivalent dans une série LTF). None si aucune bougie ne convient."""
    for i, c in enumerate(candles):
        if c["epoch"] > epoch:
            return i
    return None


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


def is_synthetic_index(symbol):
    return symbol.startswith(SYNTHETIC_INDEX_PREFIXES)


def is_killzone_exempt(symbol):
    """
    Le concept de killzone suppose une vraie session de liquidité institutionnelle
    (Londres/New York). Exempts : indices synthétiques (générés par algorithme,
    24/7) ET cryptos (marché 24/7 lui aussi, sans notion de session claire liée
    à Londres/New York comme le forex classique).
    """
    return is_synthetic_index(symbol) or symbol.startswith("cry")


def is_in_killzone(epoch):
    """
    Vérifie si un epoch tombe dans une fenêtre killzone (heure de New York).
    Ne s'applique qu'aux marchés réels — jamais appelé pour les indices synthétiques.
    """
    dt_ny = datetime.fromtimestamp(epoch, tz=ZoneInfo("America/New_York"))
    minutes_of_day = dt_ny.hour * 60 + dt_ny.minute
    for start_h, start_m, end_h, end_m in KILLZONES_NY_TIME:
        start = start_h * 60 + start_m
        end = end_h * 60 + end_m
        if start <= minutes_of_day <= end:
            return True
    return False


def compute_trade_levels(symbol, direction, range_high, range_low, sweep_candle, fvg, ob, structure_candle):
    """
    Calcule des niveaux de trade indicatifs à partir des éléments déjà détectés :
    - Entrée :
        - Marchés réels (forex, or, cryptos) : bord de l'Order Block le plus
          proche du prix actuel (le premier niveau que le prix retesterait) si un
          OB est présent, sinon milieu du FVG -- un ordre en attente (Limit/Stop),
          qui suppose un retracement avant la continuation.
        - Indices synthétiques : entrée immédiate à la clôture de la bougie de
          cassure de structure (quasi ordre au marché), PAS d'attente de
          retracement. Ces actifs sont générés par algorithme et enchaînent
          souvent des mouvements directs sans jamais revenir sur la zone OB/FVG
          -- un ordre en attente y reste fréquemment non rempli.
    - Stop loss : au-delà de l'extrême de la bougie de sweep, avec une marge de
      sécurité (STOP_LOSS_BUFFER_PCT) pour éviter une sortie sur un simple spread.
    - Take profit : le côté opposé du range de référence — étendu proportionnellement
      à la taille du range pour les indices synthétiques (SYNTHETIC_TP_EXTENSION_PCT),
      qui offrent généralement un ratio risque/récompense plus favorable.
    """
    if is_synthetic_index(symbol):
        entry = structure_candle["close"]
    elif ob:
        entry = ob["high"] if direction == "bullish" else ob["low"]
    elif fvg:
        entry = (fvg["top"] + fvg["bottom"]) / 2
    else:
        entry = None

    if direction == "bullish":
        stop_loss = sweep_candle["low"] * (1 - STOP_LOSS_BUFFER_PCT)
    else:
        stop_loss = sweep_candle["high"] * (1 + STOP_LOSS_BUFFER_PCT)

    range_size = range_high - range_low
    extended_target = is_synthetic_index(symbol)
    extension = range_size * SYNTHETIC_TP_EXTENSION_PCT if extended_target else 0

    if direction == "bullish":
        take_profit = range_high + extension
    else:
        take_profit = range_low - extension

    # Cible intermédiaire (T1) : le milieu du range, souvent visé en premier avant
    # l'extrémité opposée (T2/take_profit) -- fixe, ne dépend pas de l'extension.
    take_profit_mid = (range_high + range_low) / 2

    risk_reward = None
    risk_reward_mid = None
    if entry is not None and entry != stop_loss:
        risk = abs(entry - stop_loss)
        reward = abs(take_profit - entry)
        risk_reward = round(reward / risk, 2) if risk > 0 else None
        reward_mid = abs(take_profit_mid - entry)
        risk_reward_mid = round(reward_mid / risk, 2) if risk > 0 else None

    return {
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "take_profit_mid": take_profit_mid,
        "risk_reward": risk_reward,
        "risk_reward_mid": risk_reward_mid,
        "extended_target": extended_target,
    }


def compute_fib_ote(direction, sweep_candle, structure_candle):
    """
    Calcule la zone Fibonacci OTE (Optimal Trade Entry, 61.8%-79%) du mouvement
    impulsif entre l'extrême du sweep et la bougie de cassure de structure.
    Retourne (zone_low, zone_high), avec zone_low <= zone_high.
    """
    if direction == "bullish":
        leg_start = sweep_candle["low"]
        leg_end = structure_candle["close"]
        leg_range = leg_end - leg_start
        zone_low = leg_end - 0.79 * leg_range
        zone_high = leg_end - 0.618 * leg_range
    else:
        leg_start = sweep_candle["high"]
        leg_end = structure_candle["close"]
        leg_range = leg_start - leg_end
        zone_low = leg_end + 0.618 * leg_range
        zone_high = leg_end + 0.79 * leg_range

    return zone_low, zone_high


def is_within_fib_ote(entry, zone_low, zone_high):
    if entry is None:
        return False
    return zone_low <= entry <= zone_high


def poi_zone(fvg, ob):
    """Combine le FVG et/ou l'Order Block détectés sur le MTF en une seule zone
    de prix (low, high). Retourne None si aucun des deux n'est présent."""
    lows, highs = [], []
    if ob:
        lows.append(ob["low"])
        highs.append(ob["high"])
    if fvg:
        lows.append(fvg["bottom"])
        highs.append(fvg["top"])
    if not lows:
        return None
    return min(lows), max(highs)


def ltf_reacted_from_poi(ltf_candles, start_index, break_index, zone_low, zone_high):
    """
    Vérifie que le prix a réellement touché la zone du POI (MTF) à un moment
    donné entre le sweep et la cassure de structure (LTF) -- garantit que la
    confirmation LTF est cohérente avec le POI qui l'a "provoquée", plutôt que
    deux détections indépendantes sans lien de prix garanti.
    """
    for c in ltf_candles[start_index:break_index + 1]:
        if c["low"] <= zone_high and c["high"] >= zone_low:
            return True
    return False


def classify_order_type(direction, entry, current_price, tolerance_pct=ORDER_TYPE_TOLERANCE_PCT):
    """
    Détermine le type d'ordre (comme sur une app de trading) en comparant la zone
    d'entrée au prix actuel :
    - Buy / Sell : le prix est déjà sur la zone -> exécution immédiate
    - Buy Limit / Sell Limit : entrée en retracement, prix doit revenir en arrière
    - Buy Stop / Sell Stop : entrée en cassure, prix doit continuer dans le même sens
    """
    if entry is None or not current_price:
        return "Buy" if direction == "bullish" else "Sell"

    diff_pct = abs(current_price - entry) / current_price
    if diff_pct <= tolerance_pct:
        return "Buy" if direction == "bullish" else "Sell"

    if direction == "bullish":
        return "Buy Limit" if entry < current_price else "Buy Stop"
    else:
        return "Sell Limit" if entry > current_price else "Sell Stop"


def detect_trend(candles, swing_window=TREND_SWING_WINDOW, swing_count=TREND_SWING_COUNT,
                  sma_period=TREND_SMA_PERIOD):
    """
    Détecte la tendance de fond à partir d'une série de bougies (typiquement D1),
    en combinant deux critères qui doivent être d'accord :
    1. Structure : les `swing_count` derniers swing highs sont tous croissants ET
       les `swing_count` derniers swing lows sont tous croissants (inversement pour
       une tendance baissière) — filtre le bruit d'une comparaison à seulement 2 points.
    2. Moyenne mobile : la dernière clôture doit être au-dessus (bullish) ou en
       dessous (bearish) de la SMA sur `sma_period` bougies.
    Retourne "bullish", "bearish", "range" (les deux critères ne s'accordent pas
    ou pas de structure claire), ou None si pas assez de données.
    """
    closed = candles[:-1] if len(candles) > 1 else candles  # exclut la bougie en cours
    if len(closed) < sma_period:
        return None  # pas assez d'historique pour calculer la SMA

    highs, lows = find_swing_highs_lows(closed, swing_window, swing_window)
    if len(highs) < swing_count or len(lows) < swing_count:
        return None  # pas assez de swing points pour une structure fiable

    recent_highs = [closed[i]["high"] for i in highs[-swing_count:]]
    recent_lows = [closed[i]["low"] for i in lows[-swing_count:]]

    structure_bullish = (
        all(recent_highs[i] < recent_highs[i + 1] for i in range(len(recent_highs) - 1))
        and all(recent_lows[i] < recent_lows[i + 1] for i in range(len(recent_lows) - 1))
    )
    structure_bearish = (
        all(recent_highs[i] > recent_highs[i + 1] for i in range(len(recent_highs) - 1))
        and all(recent_lows[i] > recent_lows[i + 1] for i in range(len(recent_lows) - 1))
    )

    sma = sum(c["close"] for c in closed[-sma_period:]) / sma_period
    last_close = closed[-1]["close"]

    if structure_bullish and last_close > sma:
        return "bullish"
    if structure_bearish and last_close < sma:
        return "bearish"
    return "range"


def analyze_symbol(symbol, htf_candles_by_tf, candles_by_tf):
    """
    Analyse un symbole selon une cascade à 3 niveaux (top-down, méthodologie
    ICT classique), voir TIMEFRAME_CASCADE dans config.py :
    - Référence (HTF) : W1 (dérivé des D1), D1, H4 -- le range CRT à sweeper.
    - MTF : sweep de liquidité (manipulation) + détection du POI (FVG/Order Block).
    - Confirmation (LTF) : cassure de structure -- le déclencheur final.

    htf_candles_by_tf : dict {"D1": [...], "H4": [...]}.
    candles_by_tf : dict de toutes les séries disponibles, utilisées à la fois
    comme MTF et comme LTF selon la cascade (ex: {"D1":..., "H4":..., "H1":..., "M15":...}).
    """
    setups = []

    # Tendance de fond, calculée une fois sur D1 — sert uniquement à taguer les
    # setups à contre-tendance, jamais à les bloquer.
    trend_source = htf_candles_by_tf.get("D1")
    trend = detect_trend(trend_source) if trend_source else None

    for ref_tf, cascade in TIMEFRAME_CASCADE.items():
        if ref_tf == "W1":
            ref_range = build_weekly_range(htf_candles_by_tf.get("D1"))
        else:
            ref_range = get_reference_range(htf_candles_by_tf.get(ref_tf))

        if not ref_range:
            continue

        mtf_tf = cascade["mtf"]
        mtf_candles = candles_by_tf.get(mtf_tf)
        if not mtf_candles:
            continue

        # --- Étage MTF : manipulation (sweep) + POI (FVG/Order Block) ---
        sweeps = detect_liquidity_sweep(
            mtf_candles, ref_range["high"], ref_range["low"], ref_range["epoch"],
            granularity_seconds=GRANULARITY.get(mtf_tf),
            check_gaps=has_weekend_gaps(symbol),
        )

        # Pools de liquidité (Equal Highs/Lows) sur le MTF -- calculés une fois,
        # réutilisés pour chaque sweep détecté ci-dessous.
        high_pools, low_pools = find_liquidity_pools(mtf_candles)

        for sweep in sweeps:
            fvg = detect_fvg(mtf_candles, sweep["index"], sweep["direction"])
            ob = detect_order_block(mtf_candles, sweep["index"], sweep["direction"])

            if mtf_tf in STRICT_CONFIRMATION_TIMEFRAMES:
                if not (fvg and ob):
                    continue  # confirmation renforcée : FVG ET Order Block exigés ensemble
            else:
                if not fvg and not ob:
                    continue  # pas de POI -> setup ignoré

            # Le sweep a-t-il réellement grabbé un pool de liquidité (EQH/EQL) ?
            # Bearish -> on a swept un EQH (pool de highs) ; bullish -> un EQL.
            pools_swept = high_pools if sweep["direction"] == "bearish" else low_pools
            liquidity_grabbed = is_near_level(
                sweep["candle"]["high" if sweep["direction"] == "bearish" else "low"], pools_swept
            )

            # Killzone : uniquement pertinent sur les vrais marchés à session
            # (forex, or) -- None pour les indices synthétiques et les cryptos,
            # qui tournent 24/7 sans notion de session Londres/New York claire.
            if is_killzone_exempt(symbol):
                in_killzone = None
            else:
                in_killzone = is_in_killzone(sweep["candle"]["epoch"])
                if REQUIRE_KILLZONE_FOR_REAL_MARKETS and not in_killzone:
                    continue  # sweep hors killzone -> setup ignoré

            # --- Étage LTF (confirmation) : cassure de structure = déclencheur ---
            for confirmation_tf in cascade["confirmation"]:
                ltf_candles = candles_by_tf.get(confirmation_tf)
                if not ltf_candles:
                    continue

                start_index = find_index_after_epoch(ltf_candles, sweep["candle"]["epoch"])
                if start_index is None:
                    continue

                swing_window = STRUCTURE_SWING_WINDOW.get(confirmation_tf, DEFAULT_STRUCTURE_SWING_WINDOW)
                structure = detect_structure_shift(
                    ltf_candles, start_index, sweep["direction"],
                    left=swing_window, right=swing_window
                )
                if not structure:
                    continue

                # Cohérence POI (MTF) <-> cassure de structure (LTF) : le prix
                # doit avoir réellement touché la zone du POI entre le sweep et
                # la cassure, sinon les deux détections ne parlent pas du même
                # mouvement -> setup ignoré.
                zone = poi_zone(fvg, ob)
                if not zone or not ltf_reacted_from_poi(ltf_candles, start_index, structure["break_index"], *zone):
                    continue

                structure_candle = ltf_candles[structure["break_index"]]

                trade_levels = compute_trade_levels(
                    symbol, sweep["direction"], ref_range["high"], ref_range["low"],
                    sweep["candle"], fvg, ob, structure_candle
                )

                # Le stop loss tombe-t-il lui-même sur un pool (EQH/EQL opposé) ?
                # Si oui, on ne veut pas être la liquidité à notre tour -> marge
                # additionnelle pour l'écarter du niveau détecté.
                opposite_pools = high_pools if sweep["direction"] == "bullish" else low_pools
                if is_near_level(trade_levels["stop_loss"], opposite_pools):
                    buffer = trade_levels["stop_loss"] * STOP_LOSS_POOL_BUFFER_PCT
                    if sweep["direction"] == "bullish":
                        trade_levels["stop_loss"] -= buffer
                    else:
                        trade_levels["stop_loss"] += buffer
                    # Le stop a changé -> le R:R doit être recalculé en conséquence.
                    if trade_levels["entry"] is not None:
                        risk = abs(trade_levels["entry"] - trade_levels["stop_loss"])
                        if risk > 0:
                            reward = abs(trade_levels["take_profit"] - trade_levels["entry"])
                            trade_levels["risk_reward"] = round(reward / risk, 2)

                # Filtre R:R minimum : un setup dont le ratio ne l'atteint pas est ignoré.
                if trade_levels["risk_reward"] is None or trade_levels["risk_reward"] < MIN_RISK_REWARD:
                    continue

                fib_zone_low, fib_zone_high = compute_fib_ote(sweep["direction"], sweep["candle"], structure_candle)
                fib_ote_confirmed = is_within_fib_ote(trade_levels["entry"], fib_zone_low, fib_zone_high)

                if REQUIRE_FIB_OTE and not fib_ote_confirmed:
                    continue  # entrée hors zone Fibonacci OTE -> setup ignoré

                counter_trend = (
                    (trend == "bullish" and sweep["direction"] == "bearish")
                    or (trend == "bearish" and sweep["direction"] == "bullish")
                )

                current_price = ltf_candles[-1]["close"]
                order_type = classify_order_type(sweep["direction"], trade_levels["entry"], current_price)

                setups.append({
                    "symbol": symbol,
                    "reference_tf": ref_tf,
                    "mtf": mtf_tf,
                    "confirmation_tf": confirmation_tf,
                    "ref_epoch": ref_range["epoch"],
                    "direction": sweep["direction"],
                    "order_type": order_type,
                    "range_high": ref_range["high"],
                    "range_low": ref_range["low"],
                    "sweep_candle": sweep["candle"],
                    "structure_break_level": structure["level"],
                    "entry": trade_levels["entry"],
                    "stop_loss": trade_levels["stop_loss"],
                    "take_profit": trade_levels["take_profit"],
                    "take_profit_mid": trade_levels["take_profit_mid"],
                    "risk_reward": trade_levels["risk_reward"],
                    "risk_reward_mid": trade_levels["risk_reward_mid"],
                    "extended_target": trade_levels["extended_target"],
                    "fib_ote_confirmed": fib_ote_confirmed,
                    "trend": trend,
                    "counter_trend": counter_trend,
                    "in_killzone": in_killzone,
                    "liquidity_grabbed": liquidity_grabbed,
                    "fvg": fvg,
                    "order_block": ob,
                })
    return setups
