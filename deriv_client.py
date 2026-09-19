import asyncio
import json
import time
import websockets

from config import DERIV_WS_URL, CANDLE_COUNT


async def _fetch_candles_on_connection(ws, symbol, granularity, count, timeout=15):
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
    response = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))

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


# --- Pagination pour le backtest : récupère un historique long (plusieurs mois)
# en enchaînant plusieurs requêtes, l'API Deriv limitant le nombre de bougies
# par appel (généralement 5000 max). Jamais utilisé par le scan en production.
async def fetch_history_range(symbol, granularity, target_start_epoch, count_per_call=5000, timeout=20):
    all_candles = {}
    cursor_end = int(time.time())

    async with websockets.connect(DERIV_WS_URL, ping_interval=20) as ws:
        while cursor_end > target_start_epoch:
            request = {
                "ticks_history": symbol,
                "adjust_start_time": 1,
                "count": count_per_call,
                "end": cursor_end,
                "start": 1,
                "style": "candles",
                "granularity": granularity,
            }
            await ws.send(json.dumps(request))
            try:
                response = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
            except Exception as e:
                print(f"  [{symbol}] Erreur de pagination : {e}")
                break

            if "error" in response:
                print(f"  [{symbol}] Erreur API : {response['error']['message']}")
                break

            candles = response.get("candles", [])
            if not candles:
                break

            for c in candles:
                epoch = c["epoch"]
                all_candles[epoch] = {
                    "epoch": epoch,
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"]),
                }

            earliest = min(c["epoch"] for c in candles)
            if earliest >= cursor_end:
                break  # pas de progression -> éviter une boucle infinie
            cursor_end = earliest - 1
            await asyncio.sleep(0.2)

    sorted_candles = sorted(all_candles.values(), key=lambda c: c["epoch"])
    trimmed = [c for c in sorted_candles if c["epoch"] >= target_start_epoch]
    return trimmed or sorted_candles


def get_history_range(symbol, granularity, target_start_epoch):
    return asyncio.run(fetch_history_range(symbol, granularity, target_start_epoch))
