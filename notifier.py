import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SYNTHETIC_INDEX_PREFIXES


def send_telegram_message(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID manquant (variables d'environnement)."
        )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    response = requests.post(url, json=payload, timeout=15)
    response.raise_for_status()
    return response.json()


def is_synthetic_index(symbol: str) -> bool:
    return symbol.startswith(SYNTHETIC_INDEX_PREFIXES)


SYNTHETIC_DISPLAY_NAMES = {
    "R_10": "Volatility 10 Index",
    "R_25": "Volatility 25 Index",
    "R_50": "Volatility 50 Index",
    "R_75": "Volatility 75 Index",
    "R_100": "Volatility 100 Index",
    "1HZ10V": "Volatility 10 (1s) Index",
    "1HZ15V": "Volatility 15 (1s) Index",
    "1HZ25V": "Volatility 25 (1s) Index",
    "1HZ30V": "Volatility 30 (1s) Index",
    "1HZ50V": "Volatility 50 (1s) Index",
    "1HZ75V": "Volatility 75 (1s) Index",
    "1HZ90V": "Volatility 90 (1s) Index",
    "1HZ100V": "Volatility 100 (1s) Index",
    "1HZ150V": "Volatility 150 (1s) Index",
    "1HZ200V": "Volatility 200 (1s) Index",
    "1HZ250V": "Volatility 250 (1s) Index",
    "1HZ300V": "Volatility 300 (1s) Index",
    "stpRNG": "Step Index",
}


def display_symbol(symbol: str) -> str:
    if symbol.startswith("frx"):
        return symbol[3:]
    if symbol.startswith("cry"):
        return symbol[3:]
    return SYNTHETIC_DISPLAY_NAMES.get(symbol, symbol)


def format_number(value, max_decimals):
    if value is None:
        return None
    rounded = round(value, max_decimals)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.{max_decimals}f}".rstrip("0").rstrip(".")


def format_setup_message(setup: dict) -> str:
    direction_emoji = "🟢" if setup["direction"] == "bullish" else "🔴"
    direction_word = "ACHAT" if setup["direction"] == "bullish" else "VENTE"
    tp_tag = " 🌊" if setup.get("extended_target") else ""
    synthetic = is_synthetic_index(setup["symbol"])

    # Décimales max pour l'entrée/TP1/TP2 : 2 pour les indices synthétiques
    # (comme avant), 4 pour les marchés réels (forex/or/cryptos) -- le SL n'est
    # pas concerné par cette limite, il garde sa précision habituelle.
    target_decimals = 2 if synthetic else 4
    sl_decimals = 2 if synthetic else 6  # 6 = grande précision, pas de vraie limite pour le SL

    entry_raw = setup.get("entry")
    take_profit_mid = setup["take_profit_mid"]
    take_profit = setup["take_profit"]

    # Garde-fou : si l'arrondi fait coïncider deux niveaux (ex: entrée = TP1),
    # le message devient trompeur -> on assouplit temporairement la limite pour
    # CETTE alerte, jusqu'à ce que les valeurs redeviennent distinctes.
    while target_decimals < 10:
        rounded_values = [
            round(v, target_decimals) for v in (entry_raw, take_profit_mid, take_profit)
            if v is not None
        ]
        if len(rounded_values) == len(set(rounded_values)):
            break
        target_decimals += 1

    entry_value = format_number(entry_raw, target_decimals)
    order_type = setup.get("order_type", direction_word).upper()

    lines = [
        f"{direction_emoji} <b>{display_symbol(setup['symbol'])}</b>",
        f"{order_type} ({setup['reference_tf']}→{setup['confirmation_tf']})",
        f"E: {entry_value if entry_value is not None else 'n/d'}",
        f"SL: {format_number(setup['stop_loss'], sl_decimals)}",
        f"TP1: {format_number(take_profit_mid, target_decimals)}",
        f"TP2: {format_number(take_profit, target_decimals)}{tp_tag}",
    ]

    if setup.get("risk_reward"):
        lines.append(f"RR: 1:{setup['risk_reward']}")

    tags = []
    if setup.get("fib_ote_confirmed"):
        tags.append("📐")
    if setup.get("counter_trend"):
        tags.append("⚠️")
    if setup.get("in_killzone") is False:
        tags.append("⏰")
    if tags:
        lines.append(" ".join(tags))

    return "\n".join(lines)
