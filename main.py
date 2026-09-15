from config import SYMBOLS, GRANULARITY, REFERENCE_TIMEFRAMES, CONFIRMATION_TIMEFRAMES, CANDLE_COUNT
from deriv_client import get_many_candles
from strategy import analyze_symbol
from notifier import send_telegram_message, format_setup_message
from state_manager import load_state, save_state, is_new_setup, mark_setup_sent
from trade_tracker import load_stats, save_stats, add_pending, resolve_pending, summarize

# Union des TF de référence (D1, H4) et de tous les TF de confirmation (M15...),
# sans doublon, pour ne récupérer chaque série de bougies qu'une seule fois.
ALL_TIMEFRAMES = list(dict.fromkeys(REFERENCE_TIMEFRAMES + CONFIRMATION_TIMEFRAMES))


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

    for symbol in SYMBOLS:
        htf_candles_by_tf = {}
        skip_symbol = False

        for tf in REFERENCE_TIMEFRAMES:
            candles = results.get((symbol, GRANULARITY[tf]))
            if isinstance(candles, Exception) or not candles:
                print(f"[{symbol}] Erreur de récupération ({tf}) : {candles}")
                skip_symbol = True
                break
            htf_candles_by_tf[tf] = candles

        if skip_symbol:
            continue

        # Chaque TF de confirmation (M15...) est analysé indépendamment et
        # génère ses propres alertes, étiquetées séparément dans le message.
        for confirmation_tf in CONFIRMATION_TIMEFRAMES:
            ltf_candles = results.get((symbol, GRANULARITY[confirmation_tf]))
            if isinstance(ltf_candles, Exception) or not ltf_candles:
                print(f"[{symbol}] Erreur de récupération ({confirmation_tf}) : {ltf_candles}")
                continue

            setups = analyze_symbol(symbol, htf_candles_by_tf, ltf_candles, confirmation_tf)

            for setup in setups:
                if is_new_setup(state, setup):
                    message = format_setup_message(setup)
                    try:
                        send_telegram_message(message)
                        print(
                            f"[{symbol}] Alerte envoyée : {setup['direction']} sur "
                            f"{setup['reference_tf']} (confirmation {confirmation_tf})"
                        )
                    except Exception as e:
                        print(f"[{symbol}] Échec d'envoi Telegram : {e}")
                        continue
                    mark_setup_sent(state, setup)
                    add_pending(stats, setup)
                    any_new = True

    if any_new:
        save_state(state)
    else:
        print("Aucun nouveau setup détecté sur ce passage.")

    if resolved or any_new:
        save_stats(stats)

    print(summarize(stats))


if __name__ == "__main__":
    run()
