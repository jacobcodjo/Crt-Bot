"""
Backtest hors-ligne : rejoue plusieurs mois d'historique de bougies pour un
actif de chaque classe (forex/or, crypto, indice synthétique) et simule ce que
le bot aurait détecté et exécuté -- en réutilisant exactement les mêmes
fonctions que strategy.py / trade_tracker.py (pas une réimplémentation séparée).

⚠️ Ne fait JAMAIS partie du scan en production. Se lance uniquement à la main
(voir .github/workflows/backtest.yml, déclenchement manuel uniquement).

⚠️ Ce script n'a jamais pu être testé contre de vraies données Deriv avant
livraison (pas d'accès réseau dans l'environnement où il a été écrit). Le
premier lancement réel doit être considéré comme un test -- si un message
d'erreur apparaît, il faut le signaler pour correction avant de faire confiance
aux résultats.

⚠️ Simplifications par rapport au live : la tendance de fond (contre-tendance),
le tag killzone et le tag pool de liquidité ne sont pas recalculés ici (mis à
False/None par défaut) -- l'objectif est de valider le cœur de la stratégie
(sweep -> POI -> structure -> entrée -> résultat), pas de reproduire 100% des
tags informatifs du message Telegram.
"""

import time

from config import GRANULARITY, TIMEFRAME_CASCADE, MIN_RISK_REWARD, STOP_LOSS_POOL_BUFFER_PCT
from deriv_client import get_history_range
from strategy import (
    get_reference_range, build_weekly_range, detect_liquidity_sweep,
    find_liquidity_pools, is_near_level, detect_structure_shift,
    find_index_after_epoch, poi_zone, ltf_reacted_from_poi,
    detect_order_block, detect_breaker_block, detect_fvg,
    compute_trade_levels, classify_order_type, has_weekend_gaps,
    is_synthetic_index, STRICT_CONFIRMATION_TIMEFRAMES,
    STRUCTURE_SWING_WINDOW, DEFAULT_STRUCTURE_SWING_WINDOW,
)
from trade_tracker import summarize

BACKTEST_SYMBOLS = ["frxEURUSD", "frxXAUUSD", "cryBTCUSD", "R_75"]
BACKTEST_MONTHS = 6
# Fenêtre de recherche après chaque référence = N x sa propre granularité
# (approxime la durée pendant laquelle un range reste "d'actualité" avant
# qu'une nouvelle référence ne prenne le relais, comme en production).
WINDOW_MULTIPLIER = 3
REQUIRED_TIMEFRAMES = ["D1", "H4", "H1", "M15", "M5"]


def resolve_forward(direction, order_type, entry, stop_loss, take_profit, candles, start_index):
    """
    Simule, à partir de start_index, si l'ordre se remplit (pour un Limit/Stop)
    puis si le SL ou le TP est touché en premier -- même logique que
    trade_tracker.resolve_pending, appliquée directement sur l'historique.
    """
    filled = order_type in ("Buy", "Sell")
    fill_index = start_index if filled else None

    if not filled:
        for i in range(start_index, len(candles)):
            c = candles[i]
            if order_type == "Buy Limit":
                hit = c["low"] <= entry
            elif order_type == "Sell Limit":
                hit = c["high"] >= entry
            elif order_type == "Buy Stop":
                hit = c["high"] >= entry
            elif order_type == "Sell Stop":
                hit = c["low"] <= entry
            else:
                hit = True
            if hit:
                filled = True
                fill_index = i
                break

    if not filled:
        return "EXPIRE"

    for i in range(fill_index + 1, len(candles)):
        c = candles[i]
        if direction == "bullish":
            hit_tp = c["high"] >= take_profit
            hit_sl = c["low"] <= stop_loss
        else:
            hit_tp = c["low"] <= take_profit
            hit_sl = c["high"] >= stop_loss

        if hit_tp and hit_sl:
            return "SL"  # même hypothèse prudente qu'en production
        if hit_sl:
            return "SL"
        if hit_tp:
            return "TP"

    return "EXPIRE"  # jamais résolu dans l'historique disponible


def backtest_tier(symbol, ref_tf, cascade, ref_series, mtf_series, ltf_series_by_conf):
    """Rejoue un seul niveau de la cascade (ex: D1 -> H4 -> H1) sur tout l'historique."""
    results = []
    mtf_tf = cascade["mtf"]
    granularity_ref = 604800 if ref_tf == "W1" else GRANULARITY[ref_tf]

    lookback = 5
    if not ref_series or len(ref_series) <= lookback + 1:
        return results

    for i in range(lookback, len(ref_series) - 1):
        if ref_tf == "W1":
            ref_range = build_weekly_range(ref_series[:i + 2])
        else:
            ref_range = get_reference_range(ref_series[:i + 2])
        if not ref_range:
            continue

        window_end = ref_range["epoch"] + WINDOW_MULTIPLIER * granularity_ref
        mtf_window = [c for c in mtf_series if ref_range["epoch"] < c["epoch"] <= window_end]
        if not mtf_window:
            continue

        sweeps = detect_liquidity_sweep(
            mtf_window, ref_range["high"], ref_range["low"], ref_range["epoch"],
            granularity_seconds=GRANULARITY[mtf_tf], check_gaps=has_weekend_gaps(symbol),
        )
        if not sweeps:
            continue

        high_pools, low_pools = find_liquidity_pools(mtf_window)

        for sweep in sweeps:
            fvg = detect_fvg(mtf_window, sweep["index"], sweep["direction"])
            ob = detect_order_block(mtf_window, sweep["index"], sweep["direction"])

            if mtf_tf in STRICT_CONFIRMATION_TIMEFRAMES:
                if not (fvg and ob):
                    continue
            elif not fvg and not ob:
                continue

            for confirmation_tf in cascade["confirmation"]:
                ltf_series = ltf_series_by_conf.get(confirmation_tf)
                if not ltf_series:
                    continue

                start_index = find_index_after_epoch(ltf_series, sweep["candle"]["epoch"])
                if start_index is None:
                    continue

                swing_window = STRUCTURE_SWING_WINDOW.get(confirmation_tf, DEFAULT_STRUCTURE_SWING_WINDOW)
                structure = detect_structure_shift(
                    ltf_series, start_index, sweep["direction"],
                    left=swing_window, right=swing_window
                )
                if not structure:
                    continue

                zone = poi_zone(fvg, ob)
                if not zone or not ltf_reacted_from_poi(
                    ltf_series, start_index, structure["break_index"], *zone
                ):
                    continue

                structure_candle = ltf_series[structure["break_index"]]

                ltf_window_size = max(1, structure["break_index"] - start_index)
                entry_poi = None
                ltf_ob = detect_order_block(
                    ltf_series, structure["break_index"], sweep["direction"], window=ltf_window_size
                )
                if ltf_ob:
                    entry_poi = {"kind": "ob", "high": ltf_ob["high"], "low": ltf_ob["low"]}
                else:
                    ltf_breaker = detect_breaker_block(ltf_series, structure["pivot_index"], sweep["direction"])
                    if ltf_breaker:
                        entry_poi = {"kind": "breaker", "high": ltf_breaker["high"], "low": ltf_breaker["low"]}
                    else:
                        ltf_fvg = detect_fvg(ltf_series, structure["break_index"], sweep["direction"])
                        if ltf_fvg:
                            entry_poi = {"kind": "fvg", "top": ltf_fvg["top"], "bottom": ltf_fvg["bottom"]}

                if entry_poi is None and not is_synthetic_index(symbol):
                    continue

                trade_levels = compute_trade_levels(
                    symbol, sweep["direction"], ref_range["high"], ref_range["low"],
                    sweep["candle"], entry_poi, structure_candle
                )

                opposite_pools = high_pools if sweep["direction"] == "bullish" else low_pools
                if is_near_level(trade_levels["stop_loss"], opposite_pools):
                    buffer = trade_levels["stop_loss"] * STOP_LOSS_POOL_BUFFER_PCT
                    if sweep["direction"] == "bullish":
                        trade_levels["stop_loss"] -= buffer
                    else:
                        trade_levels["stop_loss"] += buffer
                    if trade_levels["entry"] is not None:
                        risk = abs(trade_levels["entry"] - trade_levels["stop_loss"])
                        if risk > 0:
                            reward = abs(trade_levels["take_profit"] - trade_levels["entry"])
                            trade_levels["risk_reward"] = round(reward / risk, 2)

                if trade_levels["risk_reward"] is None or trade_levels["risk_reward"] < MIN_RISK_REWARD:
                    continue

                current_price = ltf_series[start_index]["close"]
                order_type = classify_order_type(sweep["direction"], trade_levels["entry"], current_price)

                outcome = resolve_forward(
                    sweep["direction"], order_type, trade_levels["entry"],
                    trade_levels["stop_loss"], trade_levels["take_profit"],
                    ltf_series, structure["break_index"] + 1
                )

                results.append({
                    "symbol": symbol,
                    "direction": sweep["direction"],
                    "order_type": order_type,
                    "counter_trend": False,  # non recalculé en backtest (simplification)
                    "risk_reward": trade_levels["risk_reward"],
                    "result": outcome,
                    "resolved_epoch": sweep["candle"]["epoch"],
                })

    return results


def run():
    end_epoch = int(time.time())
    start_epoch = end_epoch - BACKTEST_MONTHS * 30 * 86400

    all_history = []

    for symbol in BACKTEST_SYMBOLS:
        print(f"\n=== {symbol} : récupération de l'historique ({BACKTEST_MONTHS} mois) ===")
        series = {}
        for tf in REQUIRED_TIMEFRAMES:
            print(f"  {tf}...")
            candles = get_history_range(symbol, GRANULARITY[tf], start_epoch)
            print(f"  {tf} : {len(candles)} bougies récupérées.")
            series[tf] = candles

        symbol_history = []
        for ref_tf, cascade in TIMEFRAME_CASCADE.items():
            ref_series = series.get("D1") if ref_tf == "W1" else series.get(ref_tf)
            mtf_series = series.get(cascade["mtf"])
            ltf_series_by_conf = {tf: series.get(tf) for tf in cascade["confirmation"]}

            results = backtest_tier(symbol, ref_tf, cascade, ref_series, mtf_series, ltf_series_by_conf)
            print(f"  Cascade {ref_tf}->{cascade['mtf']}->{cascade['confirmation']} : {len(results)} setup(s)")
            symbol_history.extend(results)

        all_history.extend(symbol_history)
        print(f"\n--- Résumé {symbol} ---")
        print(summarize({"history": symbol_history}))

    print("\n=== Résumé global (3 actifs, 6 mois) ===")
    print(summarize({"history": all_history}))


if __name__ == "__main__":
    run()
