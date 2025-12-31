#!/usr/bin/env python3
"""
chess_uci.py — simple UCI interface for python-chess

Requirements:
    pip install python-chess

How to use as a standalone engine (stdin/stdout UCI):
    python chess_uci.py

How to use by importing and supplying a search function:

    import chess
    from chess_uci import UCIEngine

    def my_search(board, limits, stop_event, info_callback):
        # board: chess.Board()
        # limits: dict with keys like 'wtime','btime','winc','binc','movetime','depth','nodes','mate'
        # stop_event: threading.Event that is set when the engine should stop thinking
        # info_callback: function(info_dict) -> None for sending UCI "info" lines (optional)
        #
        # Return a chess.Move or UCI string for the best move.
        return chess.Move.from_uci("e2e4")

    engine = UCIEngine(search_fn=my_search, name="MyEngine", author="Me")
    engine.run()  # blocking; reads UCI commands from stdin/stdout

Notes:
- You must provide your own search / evaluation code. The default search_fn raises NotImplementedError.
- info_callback can be used to send periodic "info" updates (score, depth, nodes, nps) via UCI.
"""

from __future__ import annotations
import sys
import threading
import time
import traceback
from typing import Callable, Optional, Any, Dict

import chess

# Types
SearchFnType = Callable[[chess.Board, Dict[str, Any], threading.Event, Optional[Callable[[Dict[str, Any]], None]]], Any]


class UCIEngine:
    def __init__(self, search_fn: Optional[SearchFnType] = None, name: str = "PythonUCIEngine", author: str = "Author", logger: Optional[Callable[[str], None]] = None):
        """
        Create a UCIEngine.

        search_fn signature: (board, limits, stop_event, info_callback) -> chess.Move or UCI string
            - board: chess.Board (current position)
            - limits: dict describing search limits (see parse_go)
            - stop_event: threading.Event set when the search should stop
            - info_callback: function(info_dict) to send periodic info lines; optional

        If search_fn is None, the engine will raise NotImplementedError on 'go'.
        """
        self.name = name
        self.author = author
        self.search_fn = search_fn or self._default_search_fn
        self.logger = logger or (lambda s: None)
        self.board = chess.Board()
        self.options = {}
        self.search_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.ponder = False
        self.ponder_move = None
        self._search_lock = threading.Lock()
        self._last_info_time = 0.0

    def _default_search_fn(self, board, limits, stop_event, info_callback=None):
        raise NotImplementedError("No search function provided. Set search_fn when creating UCIEngine.")

    def _send(self, line: str):
        # send line to stdout (UCI expects newline-terminated lines)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
        self.logger(f"-> {line}")

    def _send_info(self, info: Dict[str, Any]):
        """
        Send an 'info' line to the GUI. info is a dict (e.g. {'score': {'cp': 12}, 'depth': 5, 'nodes': 12345})
        This helper converts it into a simple UCI info string. You can extend it as needed.
        """
        parts = ["info"]
        # depth
        if "depth" in info:
            parts += ["depth", str(info["depth"])]
        if "seldepth" in info:
            parts += ["seldepth", str(info["seldepth"])]
        if "score" in info:
            sc = info["score"]
            if isinstance(sc, dict):
                if "cp" in sc:
                    parts += ["score", "cp", str(sc["cp"])]
                elif "mate" in sc:
                    parts += ["score", "mate", str(sc["mate"])]
            else:
                parts += ["score", str(sc)]
        if "nodes" in info:
            parts += ["nodes", str(info["nodes"])]
        if "nps" in info:
            parts += ["nps", str(info["nps"])]
        if "pv" in info:
            # pv as list of moves or string
            pv = info["pv"]
            if isinstance(pv, (list, tuple)):
                pvstr = " ".join(m.uci() if isinstance(m, chess.Move) else str(m) for m in pv)
            else:
                pvstr = str(pv)
            parts += ["pv", pvstr]
        # time
        if "time" in info:
            parts += ["time", str(int(info["time"] * 1000))]
        self._send(" ".join(parts))

    def run(self):
        """
        Main loop: read UCI commands from stdin and respond.
        Blocks until 'quit' is received.
        """
        try:
            while True:
                line = sys.stdin.readline()
                if line == "":
                    # EOF
                    break
                line = line.strip()
                if not line:
                    continue
                self.logger(f"<- {line}")
                try:
                    stop = self._handle_line(line)
                    if stop:
                        break
                except Exception:
                    traceback.print_exc(file=sys.stderr)
        finally:
            # Ensure any running search thread is stopped
            self._stop_search(wait=True)

    def _handle_line(self, line: str) -> bool:
        tokens = line.split()
        cmd = tokens[0]

        if cmd == "uci":
            self._cmd_uci()
        elif cmd == "isready":
            self._cmd_isready()
        elif cmd == "setoption":
            self._cmd_setoption(tokens[1:])
        elif cmd == "ucinewgame":
            self._cmd_ucinewgame()
        elif cmd == "position":
            self._cmd_position(tokens[1:])
        elif cmd == "go":
            self._cmd_go(tokens[1:])
        elif cmd == "stop":
            self._cmd_stop()
        elif cmd == "ponderhit":
            self._cmd_ponderhit()
        elif cmd == "quit":
            self._cmd_quit()
            return True
        else:
            # Unknown or ignored commands (e.g., debug, perft, register)
            self.logger(f"Unknown command: {line}")
        return False

    def _cmd_uci(self):
        self._send(f"id name {self.name}")
        self._send(f"id author {self.author}")
        # options (none by default — user can implement by setting self.options)
        for opt_name, opt_info in self.options.items():
            # opt_info can be a dict with keys type, default, min, max, var
            line = f"option name {opt_name} type {opt_info.get('type','spin')}"
            if "default" in opt_info:
                line += f" default {opt_info['default']}"
            if "min" in opt_info:
                line += f" min {opt_info['min']}"
            if "max" in opt_info:
                line += f" max {opt_info['max']}"
            if "var" in opt_info:
                for v in opt_info["var"]:
                    line += f" var {v}"
            self._send(line)
        self._send("uciok")

    def _cmd_isready(self):
        # If engine requires setup, do it here.
        self._send("readyok")

    def _cmd_setoption(self, tokens):
        # tokens like: ['name', 'Hash', 'value', '128']
        # Basic parsing
        name = None
        value = None
        i = 0
        while i < len(tokens):
            if tokens[i] == "name":
                i += 1
                start = i
                while i < len(tokens) and tokens[i] != "value":
                    i += 1
                name = " ".join(tokens[start:i])
            elif tokens[i] == "value":
                i += 1
                value = " ".join(tokens[i:])
                break
            else:
                i += 1
        if name is None:
            return
        self.options[name] = {"type": "string", "default": value}
        # Allow the host program to watch for options by overriding set_option
        try:
            self.set_option(name, value)
        except Exception:
            traceback.print_exc(file=sys.stderr)

    def set_option(self, name: str, value: str):
        """
        Override to handle options programmatically.
        Default implementation stores them in self.options dict.
        """
        self.options[name] = {"type": "string", "default": value}

    def _cmd_ucinewgame(self):
        # Reset internal state if needed
        self.board.reset()
        self.stop_event.set()
        self._stop_search(wait=True)
        self.stop_event.clear()

    def _cmd_position(self, tokens):
        # tokens: ["startpos", "moves", ...] or ["fen", ...]
        if not tokens:
            return
        i = 0
        if tokens[0] == "startpos":
            self.board = chess.Board()
            i = 1
        elif tokens[0] == "fen":
            # fen is next 6 tokens
            fen = " ".join(tokens[1:7])
            self.board = chess.Board(fen)
            i = 7
        # optional "moves"
        if i < len(tokens) and tokens[i] == "moves":
            i += 1
            while i < len(tokens):
                mv = tokens[i]
                try:
                    move = chess.Move.from_uci(mv)
                    if move in self.board.legal_moves:
                        self.board.push(move)
                    else:
                        # try SAN? but UCI 'position' uses uci moves
                        self.logger(f"Illegal move in position: {mv}")
                        # still apply to allow continued input (some GUIs may send illegal)
                        self.board.push(move)
                except Exception:
                    self.logger(f"Failed to parse move in position: {mv}")
                i += 1

    def _parse_go(self, tokens):
        """
        Parse tokens of 'go' and return a limits dict.
        Supported tokens: wtime btime winc binc movestogo depth nodes mate movetime ponder
        """
        limits: Dict[str, Any] = {}
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t in ("wtime", "btime", "winc", "binc", "movestogo", "depth", "nodes", "mate", "movetime"):
                if i + 1 < len(tokens):
                    try:
                        limits[t] = int(tokens[i + 1])
                    except ValueError:
                        limits[t] = tokens[i + 1]
                i += 2
            elif t == "infinite":
                limits["infinite"] = True
                i += 1
            elif t == "ponder":
                limits["ponder"] = True
                i += 1
            else:
                i += 1
        # Convert milliseconds to seconds for movetime (and general time)
        # The search function will decide precise use of these numbers.
        if "movetime" in limits:
            limits["time"] = limits["movetime"] / 1000.0
        else:
            # Provide approximate single-side thinking time if wtime/btime present
            if self.board.turn == chess.WHITE and "wtime" in limits:
                limits.setdefault("time", limits["wtime"] / 1000.0)
            if self.board.turn == chess.BLACK and "btime" in limits:
                limits.setdefault("time", limits["btime"] / 1000.0)
        return limits

    def _cmd_go(self, tokens):
        limits = self._parse_go(tokens)
        self.ponder = bool(limits.get("ponder", False))
        # Start search thread
        self._start_search(limits)

    def _start_search(self, limits: Dict[str, Any]):
        with self._search_lock:
            # stop any existing search
            self._stop_search(wait=True)
            self.stop_event.clear()
            self.search_thread = threading.Thread(target=self._search_worker, args=(limits,), daemon=True)
            self.search_thread.start()

    def _stop_search(self, wait: bool):
        # Signal stop and optionally wait for thread to finish
        self.stop_event.set()
        th = self.search_thread
        self.search_thread = None
        if th is not None and wait:
            th.join(timeout=5.0)

    def _cmd_stop(self):
        self._stop_search(wait=True)

    def _cmd_ponderhit(self):
        # When GUI says ponderhit, continue with previously pondered move
        # We'll just clear ponder flag in this simple implementation
        self.ponder = False

    def _cmd_quit(self):
        self._stop_search(wait=True)
        # exit run() loop by returning True in handler

    def _search_worker(self, limits: Dict[str, Any]):
        """
        Runs in a separate thread. Calls self.search_fn and sends bestmove line when done.
        """
        try:
            # Provide info_callback to allow search function to send periodic info lines
            def info_callback(info: Dict[str, Any]):
                # Throttle info messages to avoid spamming (e.g., at most 10 per second)
                now = time.time()
                if now - self._last_info_time >= 0.05:  # ~20Hz max
                    try:
                        self._send_info(info)
                    finally:
                        self._last_info_time = now

            # Call the search function
            result = self.search_fn(self.board.copy(stack=False), limits, self.stop_event, info_callback)
            if result is None:
                # No move found (should not happen), return a legal move if any
                try:
                    move = next(iter(self.board.legal_moves))
                    best = move.uci()
                except StopIteration:
                    best = "(none)"
            else:
                if isinstance(result, chess.Move):
                    best = result.uci()
                else:
                    best = str(result)
            # If ponder requested, search_fn may return a tuple or set self.ponder_move
            ponder = None
            if isinstance(result, tuple) and len(result) >= 2:
                best = str(result[0])
                ponder = str(result[1])
            elif self.ponder_move:
                ponder = self.ponder_move

            if ponder:
                self._send(f"bestmove {best} ponder {ponder}")
            else:
                self._send(f"bestmove {best}")
        except Exception as e:
            # If an exception happens in the search, notify the GUI (debug via stderr) and send a bestmove if possible
            traceback.print_exc(file=sys.stderr)
            try:
                move = next(iter(self.board.legal_moves))
                self._send(f"bestmove {move.uci()}")
            except StopIteration:
                self._send("bestmove (none)")

    # Convenience alias
    start = run


if __name__ == "__main__":
    # If run as a script without a search function, the default search_fn raises NotImplementedError.
    # Provide a minimal no-op search that immediately returns a legal move (for testing).
    def quick_search(board, limits, stop_event, info_callback=None):
        # Very simple: choose the first legal move
        try:
            mv = next(iter(board.legal_moves))
            # Optionally send an info line
            if info_callback:
                info_callback({"depth": 1, "nodes": 1, "pv": [mv], "time": 0.0})
            return mv
        except StopIteration:
            return None

    engine = UCIEngine(search_fn=quick_search, name="MinimalPyUCI", author="ciaranmcguinness")
    engine.run()
