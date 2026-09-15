import os

# --- Deriv API ---
DERIV_APP_ID = os.environ.get("DERIV_APP_ID") or "1089"
DERIV_WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# --- Symboles surveillés (format Deriv) ---
SYMBOLS = [
    # Forex majeurs
    "frxEURUSD", "frxGBPUSD", "frxUSDJPY", "frxUSDCHF", "frxAUDUSD", "frxUSDCAD",

    # Or
    "frxXAUUSD",

    # Cryptos
    "cryBTCUSD", "cryETHUSD", "cryLTCUSD", "cryXRPUSD",

    # Volatility Index (classique)
    "R_10", "R_25", "R_50", "R_75", "R_100",
    # Volatility Index (variantes 1 seconde)
    "1HZ10V", "1HZ25V", "1HZ50V", "1HZ75V", "1HZ100V",

    # Step Index
    "stpRNG",
]

# --- Granularités (en secondes) ---
GRANULARITY = {
    "D1": 86400,
    "H4": 14400,
    "M15": 900,
    "M5": 300,
}

# Bougies de référence pour le range (utilisées ensemble)
REFERENCE_TIMEFRAMES = ["D1", "H4"]

# Timeframe utilisé pour détecter le sweep + la confirmation.
CONFIRMATION_TIMEFRAMES = ["M15"]

CANDLE_COUNT = 150
STATE_FILE = "state.json"

# Timeframes où la confirmation est renforcée : FVG ET Order Block exigés
# ensemble (au lieu de l'un ou l'autre) pour filtrer davantage le bruit.
STRICT_CONFIRMATION_TIMEFRAMES = []

# --- Gestion du risque ---

# Marge de sécurité ajoutée au-delà de l'extrême du sweep pour le stop loss,
# en pourcentage du prix (0.0005 = 0.05%). Évite d'être sorti par un simple spread.
STOP_LOSS_BUFFER_PCT = 0.0005

# Les indices synthétiques Deriv sont généralement plus volatils et permettent
# souvent des ratios risque/récompense plus élevés que le forex/or/cryptos : on
# étend leur take profit au-delà du simple bord opposé du range, proportionnellement
# à la taille du range (0.5 = +50% de la taille du range au-delà du bord opposé).
SYNTHETIC_INDEX_PREFIXES = ("R_", "1HZ", "stpRNG")
SYNTHETIC_TP_EXTENSION_PCT = 0.5
