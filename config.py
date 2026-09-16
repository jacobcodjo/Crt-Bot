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

    # Forex mineures (paires croisées, sans USD)
    "frxEURGBP", "frxEURJPY", "frxEURCHF", "frxEURAUD", "frxEURCAD", "frxEURNZD",
    "frxGBPJPY", "frxGBPCHF", "frxGBPAUD", "frxGBPCAD", "frxGBPNZD",
    "frxAUDCAD", "frxAUDCHF",
    "frxCADCHF", "frxCADJPY",
    "frxCHFJPY",
    "frxNZDCAD", "frxNZDCHF",

    # Or
    "frxXAUUSD",

    # Cryptos
    "cryBTCUSD", "cryETHUSD", "cryLTCUSD", "cryXRPUSD",

    # Volatility Index — classique (tick/2s), existe seulement pour 10/25/50/75/100
    "R_10", "R_25", "R_50", "R_75", "R_100",
    # Volatility Index — variantes 1 seconde (liste complète actuelle chez Deriv)
    "1HZ10V", "1HZ15V", "1HZ25V", "1HZ30V", "1HZ50V", "1HZ75V",
    "1HZ90V", "1HZ100V", "1HZ150V", "1HZ200V", "1HZ250V", "1HZ300V",

    # Step Index
    "stpRNG",
]

# --- Granularités (en secondes) ---
# Pas d'entrée W1 : Deriv ne supporte pas de façon fiable une granularité
# hebdomadaire directe. Le range W1 est calculé en agrégeant les bougies D1
# déjà récupérées (voir build_weekly_range dans strategy.py).
GRANULARITY = {
    "D1": 86400,
    "H4": 14400,
    "H1": 3600,
    "M30": 1800,
    "M15": 900,
    "M5": 300,
}

# Bougies de référence pour le range. "W1" est dérivé des bougies D1 (voir ci-dessus).
REFERENCE_TIMEFRAMES = ["W1", "D1", "H4"]

# Répartition des timeframes de confirmation par référence : plus le range de
# référence est large, plus la confirmation doit être sur un TF proportionnellement
# plus grand, pour éviter le bruit d'une confirmation trop fine par rapport à
# l'ampleur du range (ex: confirmer un range hebdomadaire sur M15 serait disproportionné).
REFERENCE_CONFIRMATION_MAP = {
    "W1": ["H4"],
    "D1": ["H1"],
    "H4": ["M15"],
}

# Fenêtre utilisée pour détecter les swing points lors de la cassure de structure
# (detect_structure_shift), par timeframe de confirmation. Une fenêtre plus petite
# = pivots plus proches, cassure de structure détectée plus vite (plus réactif,
# un peu plus sensible au bruit). TF non listé -> DEFAULT_STRUCTURE_SWING_WINDOW.
STRUCTURE_SWING_WINDOW = {
    "M15": 1,
}
DEFAULT_STRUCTURE_SWING_WINDOW = 2

# Tolérance (en % du prix) pour considérer que le prix actuel est "sur" la zone
# d'entrée -> ordre au marché (Buy/Sell) plutôt qu'un ordre en attente (Limit/Stop).
ORDER_TYPE_TOLERANCE_PCT = 0.0005

# Killzones (heure de New York) : fenêtres horaires où un sweep a une vraie
# validité institutionnelle. Ne s'applique QUE sur les marchés réels (forex, or,
# cryptos) -- les indices synthétiques Deriv sont générés par algorithme, tournent
# 24/7 et n'ont aucune session de liquidité réelle à manipuler, donc le concept
# de killzone ne leur est pas applicable (jamais de tag/filtre sur ces actifs).
KILLZONES_NY_TIME = [
    (3, 0, 6, 0),     # Londres
    (8, 30, 11, 30),  # New York
]
# False (par défaut) : la killzone est juste indiquée dans le message (tag
# informatif si le sweep est HORS killzone). True : setup hors killzone ignoré
# (filtre bloquant), uniquement sur les marchés réels.
REQUIRE_KILLZONE_FOR_REAL_MARKETS = False

CANDLE_COUNT = 150
STATE_FILE = "state.json"
STATS_FILE = "trade_stats.json"

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

# Ratio risque/récompense minimum exigé pour qu'une alerte soit envoyée.
MIN_RISK_REWARD = 3.0

# Confirmation Fibonacci OTE (Optimal Trade Entry) : vérifie que l'entrée tombe
# dans la zone de retracement 61.8%-79% du mouvement impulsif suivant le sweep.
# Si False, la zone est juste indiquée dans le message (informatif, pas un filtre).
# Si True, un setup dont l'entrée est hors zone OTE est purement et simplement ignoré.
REQUIRE_FIB_OTE = False

# Détection de la tendance de fond (D1) — combine 3 critères :
# 1. Fenêtre de détection des swing points élargie (moins de bruit court terme)
# 2. Exige 3 swing highs ET 3 swing lows consécutifs, tous croissants (ou décroissants)
# 3. Confirmation par une moyenne mobile simple (SMA) sur les clôtures D1
# Un setup à contre-tendance n'est jamais bloqué, juste signalé par un tag
# d'avertissement dans le message Telegram.
TREND_SWING_WINDOW = 4
TREND_SWING_COUNT = 3
TREND_SMA_PERIOD = 50
