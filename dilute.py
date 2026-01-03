import chess
from py_uci import UCIEngine
import random

def rand(board, limits, stop_event, info_callback, options):
    if random.randrange(0, 100) < options.get("Dilution"):
        legal_moves = list(board.legal_moves)
        move = random.choice(legal_moves)
        return move.uci()
    else:
        options_engine_path = options.get("Engine Path")
        eng = chess.engine.SimpleEngine.popen_uci(options_engine_path)
        result = eng.play(board, chess.engine.Limit(time=limits.get("time", 1.0)))
        return result.move.uci()



engine = UCIEngine(search_fn=rand, name="Dilute", author="Me", FrontendTimer=False)
engine.register_option("Dilution", "spin", 0, 100, 50, "Dilution level (0-100)")
engine.register_option("Engine Path", "string", default="./stockfish")
engine.run()  # blocking; reads UCI commands from stdin/stdout