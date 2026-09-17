from config import SYMBOLS, GRANULARITY, REFERENCE_CONFIRMATION_MAP, CANDLE_COUNT
from deriv_client import get_many_candles
from strategy import analyze_symbol
from notifier import send_telegram_message, format_setup_message
from state_manager import load_state, save_state, is_new_setup, mark_setup_sent, prune_state
from trade_tracker import (
    load_stats, save_stats, add_pending, resolve_pending, summarize,
    expire_stale_pending, prune_history,
)

# TF de référence réellement récupérés via l'API (W1 est dérivé des bougies D1,
# pas de requête séparée nécessaire).
FETCHED_REFERENCE_TIMEFRAMES = ["D1", "H4"]

# Union de tous les TF de confirmation utilisés, toutes références confondues.
CONFIRMATION_TIMEFRAMES = sorted({
    tf for tfs in REFERENCE_CONFIRMATION_MAP.values() for tf in tfs
})

# Toutes les granularités à récupérer (références + confirmations, sans doublon
# même si un TF sert aux deux, ex: H4 référence ET confirmation pour W1).
ALL_TIMEFRAMES = list(dict.fromkeys(FETCHED_REFERENCE_TIMEFRAMES + CONFIRMATION_TIMEFRAMES))


def build_specs():
    """Construit la liste de toutes les requêtes (symbole, granularité, count)
    à envoyer sur l'unique connexion WebSocket."""
    specs = []
    for symbol in SYMBOLS:
        for tf in ALL_TIMEFRAMES:
            specs.append((symbol, GRANULARITY[tf], CANDLE_COUNT))
    return specs


def run():
    state = load_state()
    stats = load_stats()
    any_new = False

    specs = build_specs()
    print(f"Récupération de {len(specs)} séries de bougies sur une seule connexion WebSocket...")
    results = get_many_candles(specs)

    def candles_lookup(symbol, confirmation_tf):
        candles = results.get((symbol, GRANULARITY[confirmation_tf]))
        return candles if candles and not isinstance(candles, Exception) else None

    # Résolution des trades en attente : vérifie si le SL ou le TP a été touché
    # en premier, à partir des bougies fraîchement récupérées.
    resolved = resolve_pending(stats, candles_lookup)
    if resolved:
        print(f"{len(resolved)} trade(s) résolu(s) ce passage.")

    # Nettoyage automatique : verrous de range trop vieux, ordres jamais remplis
    # après PENDING_MAX_AGE_DAYS (expirés), historique trop ancien.
    pruned_state_count = prune_state(state)
    expired_count = expire_stale_pending(stats)
    pruned_history_count = prune_history(stats)
    if pruned_state_count:
        print(f"{pruned_state_count} entrée(s) de state.json purgée(s) (trop anciennes).")
    if expired_count:
        print(f"{expired_count} trade(s) en attente expiré(s) (jamais rempli).")
    if pruned_history_count:
        print(f"{pruned_history_count} entrée(s) d'historique purgée(s) (trop anciennes).")

    for symbol in SYMBOLS:
        htf_candles_by_tf = {}
        skip_symbol = False

        for tf in FETCHED_REFERENCE_TIMEFRAMES:
            candles = results.get((symbol, GRANULARITY[tf]))
            if isinstance(candles, Exception) or not candles:
                print(f"[{symbol}] Erreur de récupération ({tf}) : {candles}")
                skip_symbol = True
                break
            htf_candles_by_tf[tf] = candles

        if skip_symbol:
            continue

        ltf_candles_by_tf = {}
        for tf in CONFIRMATION_TIMEFRAMES:
            candles = results.get((symbol, GRANULARITY[tf]))
            if not isinstance(candles, Exception) and candles:
                ltf_candles_by_tf[tf] = candles

        setups = analyze_symbol(symbol, htf_candles_by_tf, ltf_candles_by_tf)

        for setup in setups:
            if is_new_setup(state, setup):
                message = format_setup_message(setup)
                try:
                    send_telegram_message(message)
                    print(
                        f"[{symbol}] Alerte envoyée : {setup['direction']} sur "
                        f"{setup['reference_tf']} (confirmation {setup['confirmation_tf']})"
                    )
                except Exception as e:
                    print(f"[{symbol}] Échec d'envoi Telegram : {e}")
                    continue
                mark_setup_sent(state, setup)
                add_pending(stats, setup)
                any_new = True

    if not any_new:
        print("Aucun nouveau setup détecté sur ce passage.")

    # Toujours sauvegarder : la purge (state.json) a pu retirer des entrées même
    # sans nouvelle alerte -- ne jamais perdre cet effet silencieusement.
    save_state(state)

    # Toujours sauvegarder : même sans trade résolu ni nouvelle alerte, un ordre
    # a pu passer de "en attente" à "rempli" (voir trade_tracker._check_entry_fill),
    # ou être expiré/purgé -- une progression à ne jamais perdre silencieusement.
    save_stats(stats)

    print(summarize(stats))


if __name__ == "__main__":
    run()
