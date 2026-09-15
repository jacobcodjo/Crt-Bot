import json
import os

from config import STATS_FILE


def load_stats():
    if not os.path.exists(STATS_FILE):
        return {"pending": {}, "history": []}
    with open(STATS_FILE, "r") as f:
        return json.load(f)


def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)


def track_key(setup: dict) -> str:
    return f"{setup['symbol']}_{setup['reference_tf']}_{setup['ref_epoch']}_{setup['confirmation_tf']}"


def add_pending(stats: dict, setup: dict):
    """Enregistre un setup fraîchement alerté comme trade en attente de résolution."""
    key = track_key(setup)
    stats["pending"][key] = {
        "symbol": setup["symbol"],
        "direction": setup["direction"],
        "confirmation_tf": setup["confirmation_tf"],
        "entry": setup["entry"],
        "stop_loss": setup["stop_loss"],
        "take_profit": setup["take_profit"],
        "risk_reward": setup.get("risk_reward"),
        "counter_trend": bool(setup.get("counter_trend", False)),
        "alert_epoch": setup["sweep_candle"]["epoch"],
    }


def resolve_pending(stats: dict, candles_lookup):
    """
    Parcourt les trades en attente et détermine, à partir des bougies disponibles
    depuis l'alerte, si le stop loss ou le take profit a été touché en premier.

    candles_lookup : fonction (symbol, confirmation_tf) -> liste de bougies ou None.
    Retourne la liste des clés de trades résolus lors de cet appel.
    """
    resolved_keys = []

    for key, trade in stats["pending"].items():
        candles = candles_lookup(trade["symbol"], trade["confirmation_tf"])
        if not candles:
            continue

        result = None
        for c in candles:
            if c["epoch"] <= trade["alert_epoch"]:
                continue

            if trade["direction"] == "bullish":
                hit_tp = c["high"] >= trade["take_profit"]
                hit_sl = c["low"] <= trade["stop_loss"]
            else:
                hit_tp = c["low"] <= trade["take_profit"]
                hit_sl = c["high"] >= trade["stop_loss"]

            if hit_tp and hit_sl:
                # Les deux niveaux touchés dans la même bougie : impossible de
                # savoir lequel en premier -> hypothèse prudente : le SL a cédé.
                result = "SL"
                break
            if hit_sl:
                result = "SL"
                break
            if hit_tp:
                result = "TP"
                break

        if result:
            stats["history"].append({
                "symbol": trade["symbol"],
                "direction": trade["direction"],
                "counter_trend": trade["counter_trend"],
                "risk_reward": trade["risk_reward"],
                "result": result,
            })
            resolved_keys.append(key)

    for key in resolved_keys:
        del stats["pending"][key]

    return resolved_keys


def summarize(stats: dict) -> str:
    """Construit un résumé texte du taux de réussite global et contre-tendance
    vs dans le sens de la tendance, pour affichage dans les logs GitHub Actions."""
    history = stats.get("history", [])
    if not history:
        return "Aucun trade résolu pour le moment."

    def win_rate(trades):
        if not trades:
            return None
        wins = sum(1 for t in trades if t["result"] == "TP")
        return round(100 * wins / len(trades), 1), len(trades)

    overall = win_rate(history)
    counter = win_rate([t for t in history if t["counter_trend"]])
    aligned = win_rate([t for t in history if not t["counter_trend"]])

    lines = [f"Global : {overall[0]}% de réussite sur {overall[1]} trades résolus"]
    if counter:
        lines.append(f"Contre-tendance : {counter[0]}% sur {counter[1]} trades")
    if aligned:
        lines.append(f"Dans le sens de la tendance : {aligned[0]}% sur {aligned[1]} trades")

    return " | ".join(lines)
