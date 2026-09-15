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
    direction_emoji = "🟢" if setup["direction"] == "bullish" else "🔴"
    direction_word = "ACHAT" if setup["direction"] == "bullish" else "VENTE"

    entry_part = f"Entrée {setup['entry']}" if setup.get("entry") is not None else "Entrée n/d"
    tp_tag = " 🌊" if setup.get("extended_target") else ""

    lines = [
        f"{direction_emoji} <b>{setup['symbol']}</b> — {direction_word} ({setup['reference_tf']} → {setup['confirmation_tf']})",
        f"{entry_part} | SL {setup['stop_loss']} | TP {setup['take_profit']}{tp_tag}",
    ]
    if setup.get("risk_reward"):
        lines.append(f"R:R ~1:{setup['risk_reward']}")

    return "\n".join(lines)
