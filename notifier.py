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


def format_number(value, round_it: bool):
    if value is None:
        return None
    if not round_it:
        return value  # précision brute (forex, or, cryptos)
    rounded = round(value, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def format_setup_message(setup: dict) -> str:
    direction_emoji = "🟢" if setup["direction"] == "bullish" else "🔴"
    direction_word = "ACHAT" if setup["direction"] == "bullish" else "VENTE"
    tp_tag = " 🌊" if setup.get("extended_target") else ""
    round_it = is_synthetic_index(setup["symbol"])

    if round_it:
        # Garde-fou : si l'arrondi fait coïncider deux niveaux (ex: entrée = stop),
        # le message devient trompeur -> on repasse en précision brute pour CETTE alerte.
        entry_raw = setup.get("entry")
        rounded_values = [
            round(v, 2) for v in (entry_raw, setup["stop_loss"], setup["take_profit"])
            if v is not None
        ]
        if len(rounded_values) != len(set(rounded_values)):
            round_it = False

    lines = [
        f"{direction_emoji} <b>{display_symbol(setup['symbol'])}</b>",
        f"{setup.get('order_type', direction_word).upper()} ({setup['reference_tf']} → {setup['confirmation_tf']})",
    ]

    entry_value = format_number(setup.get("entry"), round_it)
    lines.append(f"Entrée : {entry_value if entry_value is not None else 'n/d'}")
    lines.append(f"SL : {format_number(setup['stop_loss'], round_it)}")
    lines.append(f"TP : {format_number(setup['take_profit'], round_it)}{tp_tag}")

    if setup.get("risk_reward"):
        lines.append(f"R:R : ~1:{setup['risk_reward']}")

    if setup.get("fib_ote_confirmed"):
        lines.append("📐 Zone Fibo OTE (61.8-79%)")

    if setup.get("counter_trend"):
        trend_word = "haussière" if setup.get("trend") == "bullish" else "baissière"
        lines.append(f"⚠️ Contre-tendance (tendance de fond D1 {trend_word})")

    return "\n".join(lines)
