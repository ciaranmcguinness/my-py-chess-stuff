import chess
from py_uci import UCIEngine
import random

def rand(board, limits, stop_event, info_callback, _):
    try:
        mv = random.choice(list(board.legal_moves))
        # Optionally send an info line
        if info_callback:
            info_callback({"depth": 1, "nodes": 1, "pv": [mv], "time": 0.0})
        return mv
    except StopIteration:
        return None


engine = UCIEngine(search_fn=rand, name="MyEngine", author="Me", FrontendTimer=True)
engine.run()  # blocking; reads UCI commands from stdin/stdout