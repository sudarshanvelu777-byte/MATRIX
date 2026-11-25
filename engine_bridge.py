"""
engine_bridge.py
-----------------
Thin ctypes bridge between the pure-C order matching engine
(engine/liborderbook.so) and Python / Streamlit.

The C side owns all order-book state (bid/ask sorted price-level arrays,
per-price FIFO linked lists, the order index hash table and the event log).
Python only ever asks it to add/cancel orders and to dump JSON snapshots of
the book, trade tape and event log -- there is no order-matching logic on
the Python side at all.
"""

import ctypes
import json
import os

SIDE_BUY = 0
SIDE_SELL = 1
TYPE_LIMIT = 0
TYPE_MARKET = 1

_LIB_NAME = "liborderbook.so"


def _find_lib():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "..", "engine", _LIB_NAME),
        os.path.join(here, _LIB_NAME),
        _LIB_NAME,
    ]
    for c in candidates:
        if os.path.exists(c):
            return os.path.abspath(c)
    raise FileNotFoundError(
        f"Could not find {_LIB_NAME}. Build it first with: "
        f"cd engine && bash build.sh"
    )


class OrderBookEngine:
    """One instance = one independent C order book (one per traded symbol)."""

    def __init__(self):
        self._lib = ctypes.CDLL(_find_lib())
        lib = self._lib

        lib.ob_init.restype = None

        lib.ob_add_limit.argtypes = [ctypes.c_int, ctypes.c_double, ctypes.c_int]
        lib.ob_add_limit.restype = ctypes.c_int

        lib.ob_add_market.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.ob_add_market.restype = ctypes.c_int

        lib.ob_cancel.argtypes = [ctypes.c_int]
        lib.ob_cancel.restype = ctypes.c_int

        lib.ob_get_book_json.argtypes = [ctypes.c_int]
        lib.ob_get_book_json.restype = ctypes.c_void_p

        lib.ob_get_trades_json.argtypes = []
        lib.ob_get_trades_json.restype = ctypes.c_void_p

        lib.ob_get_events_json.argtypes = [ctypes.c_int]
        lib.ob_get_events_json.restype = ctypes.c_void_p

        lib.ob_free_string.argtypes = [ctypes.c_void_p]
        lib.ob_free_string.restype = None

        lib.ob_trade_count.restype = ctypes.c_int
        lib.ob_event_count.restype = ctypes.c_int

        lib.ob_init()

    def _take_string(self, ptr):
        if not ptr:
            return "null"
        s = ctypes.string_at(ptr).decode("utf-8")
        self._lib.ob_free_string(ptr)
        return s

    def reset(self):
        self._lib.ob_init()

    def add_limit(self, side: int, price: float, qty: int) -> int:
        return self._lib.ob_add_limit(side, float(price), int(qty))

    def add_market(self, side: int, qty: int) -> int:
        return self._lib.ob_add_market(side, int(qty))

    def cancel(self, order_id: int) -> bool:
        return bool(self._lib.ob_cancel(int(order_id)))

    def book(self, depth: int = 10) -> dict:
        ptr = self._lib.ob_get_book_json(depth)
        return json.loads(self._take_string(ptr))

    def trades(self) -> list:
        ptr = self._lib.ob_get_trades_json()
        return json.loads(self._take_string(ptr))

    def events(self, max_n: int = 200) -> list:
        ptr = self._lib.ob_get_events_json(max_n)
        return json.loads(self._take_string(ptr))

    def trade_count(self) -> int:
        return self._lib.ob_trade_count()

    def event_count(self) -> int:
        return self._lib.ob_event_count()
