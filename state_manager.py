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
    sweep_epoch = setup["sweep_candle"]["epoch"]
    return f"{setup['symbol']}_{setup['reference_tf']}_{setup['direction']}_{sweep_epoch}"


def is_new_setup(state: dict, setup: dict) -> bool:
    return setup_key(setup) not in state


def mark_setup_sent(state: dict, setup: dict):
    state[setup_key(setup)] = True
