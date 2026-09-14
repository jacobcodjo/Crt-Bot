import asyncio
import json
import websockets

from config import DERIV_WS_URL, CANDLE_COUNT


async def _fetch_candles_on_connection(ws, symbol, granularity, count):
    request = {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": count,
        "end": "latest",
        "start": 1,
        "style": "candles",
        "granularity": granularity,
    }
    await ws.send(json.dumps(request))
    response = json.loads(await ws.recv())

    if "error" in response:
        raise RuntimeError(f"Deriv API error for {symbol}: {response['error']['message']}")

    candles = response.get("candles", [])
    return [
        {
            "epoch": c["epoch"],
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
        }
        for c in candles
    ]


async def fetch_many(specs):
    """
    Récupère plusieurs séries de bougies en réutilisant UNE seule connexion
    WebSocket, au lieu d'en ouvrir une par requête.

    specs : liste de tuples (symbol, granularity, count)
    Retourne : dict { (symbol, granularity): [candles] ou Exception en cas d'erreur }
    """
    results = {}
    async with websockets.connect(DERIV_WS_URL, ping_interval=20) as ws:
        for symbol, granularity, count in specs:
            try:
                candles = await _fetch_candles_on_connection(ws, symbol, granularity, count)
                results[(symbol, granularity)] = candles
            except Exception as e:
                results[(symbol, granularity)] = e
            await asyncio.sleep(0.2)  # ménage l'API Deriv (évite le rate-limit)
    return results


def get_many_candles(specs):
    """Wrapper synchrone autour de fetch_many."""
    return asyncio.run(fetch_many(specs))


# --- Conservé pour compatibilité : récupération unitaire (une connexion par appel) ---
async def fetch_candles(symbol, granularity, count=CANDLE_COUNT):
    async with websockets.connect(DERIV_WS_URL, ping_interval=20) as ws:
        return await _fetch_candles_on_connection(ws, symbol, granularity, count)


def get_candles(symbol, granularity, count=CANDLE_COUNT):
    return asyncio.run(fetch_candles(symbol, granularity, count))
