from config import SYMBOLS, GRANULARITY, REFERENCE_TIMEFRAMES, CONFIRMATION_TIMEFRAME, CANDLE_COUNT
from deriv_client import get_many_candles
from strategy import analyze_symbol
from notifier import send_telegram_message, format_setup_message
from state_manager import load_state, save_state, is_new_setup, mark_setup_sent

ALL_TIMEFRAMES = REFERENCE_TIMEFRAMES + [CONFIRMATION_TIMEFRAME]


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
    any_new = False

    specs = build_specs()
    print(f"Récupération de {len(specs)} séries de bougies sur une seule connexion WebSocket...")
    results = get_many_candles(specs)

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

        ltf_candles = results.get((symbol, GRANULARITY[CONFIRMATION_TIMEFRAME]))
        if isinstance(ltf_candles, Exception) or not ltf_candles:
            print(f"[{symbol}] Erreur de récupération ({CONFIRMATION_TIMEFRAME}) : {ltf_candles}")
            continue

        setups = analyze_symbol(symbol, htf_candles_by_tf, ltf_candles)

        for setup in setups:
            if is_new_setup(state, setup):
                message = format_setup_message(setup)
                try:
                    send_telegram_message(message)
                    print(f"[{symbol}] Alerte envoyée : {setup['direction']} sur {setup['reference_tf']}")
                except Exception as e:
                    print(f"[{symbol}] Échec d'envoi Telegram : {e}")
                    continue
                mark_setup_sent(state, setup)
                any_new = True

    if any_new:
        save_state(state)
    else:
        print("Aucun nouveau setup détecté sur ce passage.")


if __name__ == "__main__":
    run()
