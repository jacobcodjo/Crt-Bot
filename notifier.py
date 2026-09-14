import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


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


def format_setup_message(setup: dict) -> str:
    direction_label = "🟢 ACHAT (bullish)" if setup["direction"] == "bullish" else "🔴 VENTE (bearish)"
    confirmations = []
    if setup.get("fvg"):
        confirmations.append("FVG")
    if setup.get("order_block"):
        confirmations.append("Order Block")

    return (
        f"<b>⚡ Setup CRT détecté</b>\n"
        f"Symbole : <b>{setup['symbol']}</b>\n"
        f"Range de référence : {setup['reference_tf']}\n"
        f"Direction : {direction_label}\n"
        f"Range : {setup['range_low']} — {setup['range_high']}\n"
        f"Cassure de structure à : {setup['structure_break_level']}\n"
        f"Confirmation(s) : {', '.join(confirmations)}\n"
        f"⚠️ Analyse automatique — à valider manuellement avant toute décision de trading."
    )
