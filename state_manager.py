import json
import os

from config import STATE_FILE


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def setup_key(setup: dict) -> str:
    # Clé basée sur le RANGE DE RÉFÉRENCE + le TF de confirmation (symbole + TF
    # référence + bougie D1/H4 + M5 ou M15), pas sur la bougie de sweep : évite les
    # alertes répétées et les signaux contraires sur un même range. Le premier setup
    # confirmé verrouille le range pour CE timeframe de confirmation jusqu'à la
    # bougie D1/H4 suivante — les pistes M5 et M15 restent indépendantes l'une de l'autre.
    return f"{setup['symbol']}_{setup['reference_tf']}_{setup['ref_epoch']}_{setup['confirmation_tf']}"


def content_key(setup: dict) -> str:
    # Second garde-fou, indépendant du range qui a déclenché le setup : si le
    # range D1 et le range H4 coïncident en valeur (fréquent juste après l'ouverture
    # d'une nouvelle bougie D1), deux clés différentes peuvent produire un message
    # strictement identique. Cette clé bloque ce cas peu importe la cause technique.
    entry = round(setup["entry"], 6) if setup.get("entry") is not None else None
    stop_loss = round(setup["stop_loss"], 6)
    take_profit = round(setup["take_profit"], 6)
    return f"content_{setup['symbol']}_{setup['direction']}_{entry}_{stop_loss}_{take_profit}"


def is_new_setup(state: dict, setup: dict) -> bool:
    return setup_key(setup) not in state and content_key(setup) not in state


def mark_setup_sent(state: dict, setup: dict):
    state[setup_key(setup)] = True
    state[content_key(setup)] = True
