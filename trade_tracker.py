import json
import os
import time

from config import STATS_FILE, PENDING_MAX_AGE_DAYS, TRADE_HISTORY_MAX_AGE_DAYS


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
    order_type = setup.get("order_type", "Buy" if setup["direction"] == "bullish" else "Sell")
    stats["pending"][key] = {
        "symbol": setup["symbol"],
        "direction": setup["direction"],
        "confirmation_tf": setup["confirmation_tf"],
        "order_type": order_type,
        "entry": setup["entry"],
        "stop_loss": setup["stop_loss"],
        "take_profit": setup["take_profit"],
        "risk_reward": setup.get("risk_reward"),
        "counter_trend": bool(setup.get("counter_trend", False)),
        "alert_epoch": setup["sweep_candle"]["epoch"],
        # Un ordre "Buy"/"Sell" (marché) est considéré rempli dès l'alerte.
        # Un ordre Limit/Stop attend que le prix atteigne réellement la zone.
        "filled": order_type in ("Buy", "Sell"),
        "fill_epoch": setup["sweep_candle"]["epoch"] if order_type in ("Buy", "Sell") else None,
    }


def _check_entry_fill(trade: dict, candles: list):
    """Parcourt les bougies pour déterminer si le prix a atteint la zone d'entrée
    d'un ordre en attente (Limit/Stop). Retourne l'epoch de remplissage, ou None."""
    entry = trade["entry"]
    if entry is None:
        return None  # pas de zone d'entrée connue -> considéré non remplissable

    for c in candles:
        if c["epoch"] <= trade["alert_epoch"]:
            continue

        if trade["order_type"] == "Buy Limit":
            hit = c["low"] <= entry
        elif trade["order_type"] == "Sell Limit":
            hit = c["high"] >= entry
        elif trade["order_type"] == "Buy Stop":
            hit = c["high"] >= entry
        elif trade["order_type"] == "Sell Stop":
            hit = c["low"] <= entry
        else:
            hit = True  # type inconnu -> ne bloque pas la résolution

        if hit:
            return c["epoch"]
    return None


def resolve_pending(stats: dict, candles_lookup):
    """
    Parcourt les trades en attente. Pour un ordre Limit/Stop, vérifie d'abord que
    le prix a bien atteint la zone d'entrée avant de chercher SL/TP -- sinon le
    trade reste "en attente" indéfiniment (l'ordre ne s'est jamais rempli).
    Une fois rempli (ou immédiatement pour un ordre au marché Buy/Sell), détermine
    si le SL ou le TP a été touché en premier.

    candles_lookup : fonction (symbol, confirmation_tf) -> liste de bougies ou None.
    Retourne la liste des clés de trades résolus lors de cet appel.
    """
    resolved_keys = []

    for key, trade in stats["pending"].items():
        candles = candles_lookup(trade["symbol"], trade["confirmation_tf"])
        if not candles:
            continue

        if not trade["filled"]:
            fill_epoch = _check_entry_fill(trade, candles)
            if fill_epoch is None:
                continue  # toujours pas rempli -> on continue à attendre
            trade["filled"] = True
            trade["fill_epoch"] = fill_epoch

        result = None
        for c in candles:
            if c["epoch"] <= trade["fill_epoch"]:
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
                "order_type": trade["order_type"],
                "counter_trend": trade["counter_trend"],
                "risk_reward": trade["risk_reward"],
                "result": result,
                "resolved_epoch": c["epoch"],
            })
            resolved_keys.append(key)

    for key in resolved_keys:
        del stats["pending"][key]

    return resolved_keys


def expire_stale_pending(stats: dict, max_age_days: float = PENDING_MAX_AGE_DAYS) -> int:
    """
    Un ordre en attente (Limit/Stop) jamais rempli après max_age_days est considéré
    expiré : le setup n'est plus d'actualité (le mouvement recherché a eu lieu sans
    lui, ou plus jamais). Archivé dans l'historique avec le résultat "EXPIRE"
    (jamais compté comme gagnant/perdant, juste comme indicateur de taux de
    remplissage -- utile notamment sur les indices synthétiques qui reviennent
    rarement sur leur zone d'entrée).
    Retourne le nombre de trades expirés.
    """
    cutoff = time.time() - max_age_days * 86400
    expired_keys = [
        key for key, trade in stats["pending"].items()
        if not trade.get("filled") and trade["alert_epoch"] < cutoff
    ]

    for key in expired_keys:
        trade = stats["pending"].pop(key)
        stats["history"].append({
            "symbol": trade["symbol"],
            "direction": trade["direction"],
            "order_type": trade["order_type"],
            "counter_trend": trade["counter_trend"],
            "risk_reward": trade["risk_reward"],
            "result": "EXPIRE",
            "resolved_epoch": time.time(),
        })

    return len(expired_keys)


def prune_history(stats: dict, max_age_days: float = TRADE_HISTORY_MAX_AGE_DAYS) -> int:
    """Retire de l'historique les entrées plus vieilles que max_age_days.
    Retourne le nombre d'entrées purgées."""
    cutoff = time.time() - max_age_days * 86400
    before = len(stats["history"])
    stats["history"] = [
        h for h in stats["history"] if h.get("resolved_epoch", time.time()) >= cutoff
    ]
    return before - len(stats["history"])


def classify_asset(symbol: str) -> str:
    if symbol.startswith("frx"):
        return "Forex/Or"
    if symbol.startswith("cry"):
        return "Crypto"
    return "Synthétiques"


def classify_order_family(order_type: str) -> str:
    if "Limit" in order_type:
        return "Limit"
    if "Stop" in order_type:
        return "Stop"
    return "Marché"


def summarize(stats: dict) -> str:
    """Construit un résumé texte du taux de réussite global, contre-tendance
    vs dans le sens de la tendance, par classe d'actif, et par famille d'ordre
    (Limit/Stop/Marché), pour affichage dans les logs GitHub Actions. Les trades
    expirés (jamais remplis) sont exclus du taux de réussite -- ils sont comptés
    séparément dans un taux de remplissage."""
    history = stats.get("history", [])
    if not history:
        return "Aucun trade résolu pour le moment."

    resolved = [h for h in history if h["result"] in ("TP", "SL")]
    expired = [h for h in history if h["result"] == "EXPIRE"]

    def win_rate(trades):
        if not trades:
            return None
        wins = sum(1 for t in trades if t["result"] == "TP")
        return round(100 * wins / len(trades), 1), len(trades)

    overall = win_rate(resolved)
    counter = win_rate([t for t in resolved if t["counter_trend"]])
    aligned = win_rate([t for t in resolved if not t["counter_trend"]])

    lines = []
    if overall:
        lines.append(f"Global : {overall[0]}% de réussite sur {overall[1]} trades résolus")
    if counter:
        lines.append(f"Contre-tendance : {counter[0]}% sur {counter[1]} trades")
    if aligned:
        lines.append(f"Dans le sens de la tendance : {aligned[0]}% sur {aligned[1]} trades")

    # Ventilation par classe d'actif
    by_class = {}
    for t in resolved:
        by_class.setdefault(classify_asset(t["symbol"]), []).append(t)
    for class_name in ("Forex/Or", "Crypto", "Synthétiques"):
        wr = win_rate(by_class.get(class_name, []))
        if wr:
            lines.append(f"{class_name} : {wr[0]}% sur {wr[1]} trades")

    # Ventilation par famille d'ordre (Limit vs Stop vs Marché)
    by_order_family = {}
    for t in resolved:
        family = classify_order_family(t.get("order_type", ""))
        by_order_family.setdefault(family, []).append(t)
    for family_name in ("Limit", "Stop", "Marché"):
        wr = win_rate(by_order_family.get(family_name, []))
        if wr:
            lines.append(f"{family_name} : {wr[0]}% sur {wr[1]} trades")

    total_with_expired = len(resolved) + len(expired)
    if expired and total_with_expired:
        fill_rate = round(100 * len(resolved) / total_with_expired, 1)
        lines.append(
            f"Taux de remplissage : {fill_rate}% ({len(resolved)} remplis / {len(expired)} expirés)"
        )

    return " | ".join(lines) if lines else "Aucun trade résolu pour le moment."
