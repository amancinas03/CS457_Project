"""
Multi-Threaded TCP Tic-Tac-Toe Server (Sprint 3).
Implements newline-delimited JSON framing, FSM game logic, thread-safe state
synchronization, and turn-aware 30-second AFK timeout enforcement.
"""

import argparse
import json
import random
import socket
import sys
import threading
import time

IP_ADDR = "0.0.0.0"
TURN_TIMEOUT = 30.0

WINNING_LINES = [
    [(0, 0), (0, 1), (0, 2)],
    [(1, 0), (1, 1), (1, 2)],
    [(2, 0), (2, 1), (2, 2)],
    [(0, 0), (1, 0), (2, 0)],
    [(0, 1), (1, 1), (2, 1)],
    [(0, 2), (1, 2), (2, 2)],
    [(0, 0), (1, 1), (2, 2)],
    [(0, 2), (1, 1), (2, 0)],
]

state_lock = threading.Lock()
match_done_event = threading.Event()

game_state = {
    "state": "WAITING_FOR_PLAYERS",
    "players": {},
    "roles": {},
    "board": [[" " for _ in range(3)] for _ in range(3)],
    "active_turn": None,
    "next_first_player": None,
    "scores": {"player_1": 0, "player_2": 0},
    "rematch_votes": {},
    "turn_start_time": 0.0,
}


def validate_port(value):
    """Validate that the port number is an integer between 1024 and 65535."""
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid port '{value}'. Must be an integer."
        ) from exc
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError(
            f"Port {port} out of range. Choose between 1024 and 65535."
        )
    return port


def parse_args():
    """Parse command-line arguments for the Tic-Tac-Toe server."""
    parser = argparse.ArgumentParser(
        description="TCP Tic-Tac-Toe Game Server."
    )
    parser.add_argument(
        "-p",
        "--port",
        type=validate_port,
        required=True,
        help="TCP port to listen on (1024-65535).",
    )
    return parser.parse_args()


def send_json(sock, payload):
    """Serialize payload to JSON with newline delimiter and send over TCP."""
    try:
        data = (json.dumps(payload) + "\n").encode("utf-8")
        sock.sendall(data)
    except OSError:
        pass


def broadcast(payload):
    """Send a JSON payload to all currently connected players."""
    for sock in list(game_state["players"].values()):
        send_json(sock, payload)


def reset_board():
    """Return an empty 3x3 Tic-Tac-Toe board."""
    return [[" " for _ in range(3)] for _ in range(3)]


def reset_match_state():
    """Reset the global game_state dictionary for a new lobby session."""
    game_state["state"] = "WAITING_FOR_PLAYERS"
    game_state["players"].clear()
    game_state["roles"].clear()
    game_state["board"] = reset_board()
    game_state["active_turn"] = None
    game_state["next_first_player"] = None
    game_state["scores"] = {"player_1": 0, "player_2": 0}
    game_state["rematch_votes"].clear()
    game_state["turn_start_time"] = 0.0


def check_winner(board):
    """Return the winning shape ('X' or 'O') if a line is complete, else None."""
    for line in WINNING_LINES:
        vals = [board[r][c] for r, c in line]
        if vals[0] != " " and vals[0] == vals[1] == vals[2]:
            return vals[0]
    return None


def is_board_full(board):
    """Return True if no empty spaces remain on the board."""
    return all(cell != " " for row in board for cell in row)


def format_overall_winner(scores):
    """Format the overall match winner string based on final scores."""
    s1 = scores["player_1"]
    s2 = scores["player_2"]
    if s1 > s2:
        return f"player_1 (Most Points: {s1} to {s2})"
    if s2 > s1:
        return f"player_2 (Most Points: {s2} to {s1})"
    return f"Tie Match ({s1} to {s2})"


def start_shape_selection():
    """Select the starting player (loser of last round, or random) to pick X/O."""
    if game_state.get("next_first_player") in ("player_1", "player_2"):
        first_player = game_state["next_first_player"]
    else:
        first_player = random.choice(["player_1", "player_2"])

    waiting_player = "player_2" if first_player == "player_1" else "player_1"

    game_state["state"] = "CHOOSE_SHAPE"
    game_state["board"] = reset_board()
    game_state["roles"].clear()
    game_state["rematch_votes"].clear()
    game_state["active_turn"] = first_player
    game_state["turn_start_time"] = time.time()

    first_sock = game_state["players"].get(first_player)
    wait_sock = game_state["players"].get(waiting_player)

    if first_sock:
        send_json(
            first_sock,
            {
                "type": "GAME_START",
                "board": game_state["board"],
                "active_turn": first_player,
                "choose_shape": True,
                "message": (
                    f"{first_player} goes first. "
                    "Please select your shape (X or O)"
                ),
            },
        )
    if wait_sock:
        send_json(
            wait_sock,
            {
                "type": "GAME_START",
                "board": game_state["board"],
                "active_turn": first_player,
                "choose_shape": False,
                "message": (
                    f"{first_player} goes first and is selecting "
                    "their shape (X or O). Please wait..."
                ),
            },
        )


def handle_forfeit(leaver_id, reason_text, is_afk=False):
    """Award forfeit win to the remaining player and close match sockets."""
    if game_state["state"] == "GAME_OVER":
        return

    game_state["state"] = "GAME_OVER"
    opponent_id = "player_2" if leaver_id == "player_1" else "player_1"
    game_state["scores"][opponent_id] += 1

    scores = dict(game_state["scores"])
    final_winner = format_overall_winner(scores)

    leaver_sock = game_state["players"].get(leaver_id)
    opponent_sock = game_state["players"].get(opponent_id)

    if is_afk and leaver_sock:
        send_json(
            leaver_sock,
            {
                "type": "GAME_OVER",
                "scores": scores,
                "final_winner": final_winner,
                "message": (
                    "[AFK] You went AFK for over 30 seconds and have been "
                    f"kicked from the lobby. {opponent_id} wins by forfeit!"
                ),
            },
        )

    if opponent_sock:
        send_json(
            opponent_sock,
            {
                "type": "GAME_OVER",
                "scores": scores,
                "final_winner": final_winner,
                "message": (
                    f"Connection to {leaver_id} lost ({reason_text}). "
                    f"{opponent_id} wins automatically! "
                    f"Final Winner: {final_winner}. Returning to lobby."
                ),
            },
        )

    for sock in list(game_state["players"].values()):
        try:
            sock.close()
        except OSError:
            pass

    match_done_event.set()


def process_message(player_id, msg):
    """Process a single decoded JSON message inside the state_lock mutex."""
    msg_type = msg.get("type")
    state = game_state["state"]
    player_sock = game_state["players"].get(player_id)
    opponent_id = "player_2" if player_id == "player_1" else "player_1"

    if msg_type == "QUIT":
        handle_forfeit(player_id, "Player quit / forfeited", is_afk=False)
        return

    if state == "CHOOSE_SHAPE" and msg_type == "SHAPE_CHOICE":
        if game_state["active_turn"] != player_id:
            send_json(
                player_sock,
                {"type": "ERROR", "message": "Not your turn to pick a shape."},
            )
            return

        choice = str(msg.get("shape", "")).strip().upper()
        if choice not in ("X", "O"):
            send_json(
                player_sock,
                {"type": "ERROR", "message": "Shape must be 'X' or 'O'."},
            )
            return

        other_shape = "O" if choice == "X" else "X"
        game_state["roles"][player_id] = choice
        game_state["roles"][opponent_id] = other_shape
        game_state["state"] = "IN_PROGRESS"
        game_state["turn_start_time"] = time.time()

        p1_role = game_state["roles"]["player_1"]
        p2_role = game_state["roles"]["player_2"]
        broadcast(
            {
                "type": "STATE_UPDATE",
                "board": game_state["board"],
                "scores": game_state["scores"],
                "active_turn": player_id,
                "message": (
                    f"Roles assigned: player_1 is {p1_role}, "
                    f"player_2 is {p2_role}. "
                    f"{player_id}, please make your move."
                ),
            }
        )
        return

    if state == "IN_PROGRESS" and msg_type == "MOVE":
        if game_state["active_turn"] != player_id:
            send_json(
                player_sock,
                {"type": "ERROR", "message": "Wait for your turn!"},
            )
            return

        try:
            row = int(msg.get("row"))
            col = int(msg.get("col"))
        except (TypeError, ValueError):
            send_json(
                player_sock,
                {"type": "ERROR", "message": "Coordinates must be integers."},
            )
            return

        if not (0 <= row <= 2 and 0 <= col <= 2):
            send_json(
                player_sock,
                {
                    "type": "ERROR",
                    "message": "Coordinates out of bounds (0-2).",
                },
            )
            return

        if game_state["board"][row][col] != " ":
            send_json(
                player_sock,
                {"type": "ERROR", "message": "Cell is already occupied!"},
            )
            return

        shape = game_state["roles"][player_id]
        game_state["board"][row][col] = shape

        winning_shape = check_winner(game_state["board"])
        if winning_shape:
            game_state["scores"][player_id] += 1
            game_state["state"] = "REMATCH_WAIT"
            game_state["next_first_player"] = opponent_id
            game_state["turn_start_time"] = time.time()
            leader = format_overall_winner(game_state["scores"])
            broadcast(
                {
                    "type": "ROUND_OVER",
                    "board": game_state["board"],
                    "scores": game_state["scores"],
                    "leader": leader,
                    "message": (
                        f"{player_id} ({shape}) wins this round!"
                    ),
                }
            )
            return

        if is_board_full(game_state["board"]):
            game_state["state"] = "REMATCH_WAIT"
            game_state["next_first_player"] = None
            game_state["turn_start_time"] = time.time()
            leader = format_overall_winner(game_state["scores"])
            broadcast(
                {
                    "type": "ROUND_OVER",
                    "board": game_state["board"],
                    "scores": game_state["scores"],
                    "leader": leader,
                    "message": "Round ended in a Draw!",
                }
            )
            return

        game_state["active_turn"] = opponent_id
        game_state["turn_start_time"] = time.time()
        broadcast(
            {
                "type": "STATE_UPDATE",
                "board": game_state["board"],
                "scores": game_state["scores"],
                "active_turn": opponent_id,
                "message": (
                    f"{player_id} placed {shape} at ({row}, {col}). "
                    f"{opponent_id}, please make your move."
                ),
            }
        )
        return

    if state == "REMATCH_WAIT" and msg_type == "REMATCH":
        vote = str(msg.get("vote", "")).strip().lower()
        game_state["rematch_votes"][player_id] = vote

        if vote in ("no", "n"):
            game_state["state"] = "GAME_OVER"
            scores = dict(game_state["scores"])
            final_winner = format_overall_winner(scores)
            broadcast(
                {
                    "type": "GAME_OVER",
                    "scores": scores,
                    "final_winner": final_winner,
                    "message": (
                        f"{player_id} declined a rematch. "
                        "Returning to lobby."
                    ),
                }
            )
            for sock in list(game_state["players"].values()):
                try:
                    sock.close()
                except OSError:
                    pass
            match_done_event.set()
            return

        if len(game_state["rematch_votes"]) == 2:
            start_shape_selection()
        else:
            game_state["turn_start_time"] = time.time()
            send_json(
                player_sock,
                {
                    "type": "INFO",
                    "message": f"Waiting for {opponent_id}'s rematch vote...",
                },
            )


def handle_client(client_socket, player_id):
    """Dedicated worker thread managing a connected player's TCP stream."""
    client_socket.settimeout(1.0)
    buffer = ""

    try:
        while not match_done_event.is_set():
            try:
                chunk = client_socket.recv(1024)
            except (socket.timeout, TimeoutError):
                with state_lock:
                    if game_state["state"] == "GAME_OVER":
                        break
                    state = game_state["state"]
                    waiting_on_player = (
                        (
                            state in ("CHOOSE_SHAPE", "IN_PROGRESS")
                            and game_state["active_turn"] == player_id
                        )
                        or (
                            state == "REMATCH_WAIT"
                            and player_id not in game_state["rematch_votes"]
                        )
                    )
                    elapsed = (
                        time.time() - game_state["turn_start_time"]
                        if game_state["turn_start_time"] > 0
                        else 0.0
                    )

                    if waiting_on_player and elapsed >= TURN_TIMEOUT:
                        print(
                            f"[SERVER] {player_id} timed out after "
                            f"{TURN_TIMEOUT:.1f}s."
                        )
                        handle_forfeit(
                            player_id,
                            "TimeoutError (30s inactivity)",
                            is_afk=True,
                        )
                        break
                continue

            if not chunk:
                with state_lock:
                    if game_state["state"] != "GAME_OVER":
                        print(f"[SERVER] {player_id} disconnected (EOF).")
                        handle_forfeit(
                            player_id,
                            "Client disconnected unexpectedly",
                            is_afk=False,
                        )
                break

            buffer += chunk.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    send_json(
                        client_socket,
                        {
                            "type": "ERROR",
                            "message": "Malformed JSON packet received.",
                        },
                    )
                    continue

                with state_lock:
                    if game_state["state"] != "GAME_OVER":
                        process_message(player_id, msg)

    except (ConnectionResetError, BrokenPipeError, OSError):
        with state_lock:
            if game_state["state"] != "GAME_OVER":
                print(f"[SERVER] Connection reset by {player_id}.")
                handle_forfeit(
                    player_id,
                    "Connection reset by peer",
                    is_afk=False,
                )
    finally:
        try:
            client_socket.close()
        except OSError:
            pass


def main():
    """Main server loop accepting pairs of players for Tic-Tac-Toe matches."""
    args = parse_args()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((IP_ADDR, args.port))
        server_sock.listen(5)
        server_sock.settimeout(1.0)

        print(
            f"[SERVER] Tic-Tac-Toe Server listening on "
            f"{IP_ADDR}:{args.port}..."
        )

        try:
            while True:
                with state_lock:
                    reset_match_state()
                    match_done_event.clear()

                print(
                    "\n[SERVER] State: WAITING_FOR_PLAYERS "
                    "(Waiting for 2 players to connect...)"
                )

                threads = []
                while len(threads) < 2:
                    try:
                        conn, addr = server_sock.accept()
                    except socket.timeout:
                        continue

                    with state_lock:
                        player_id = f"player_{len(game_state['players']) + 1}"
                        game_state["players"][player_id] = conn
                        print(
                            f"[SERVER] Accepted connection from {addr} "
                            f"as {player_id}"
                        )

                        if player_id == "player_1":
                            send_json(
                                conn,
                                {
                                    "type": "LOBBY",
                                    "player_id": player_id,
                                    "message": (
                                        "Successfully connected to server. "
                                        "Waiting for Player 2..."
                                    ),
                                },
                            )
                        else:
                            send_json(
                                conn,
                                {
                                    "type": "LOBBY",
                                    "player_id": player_id,
                                    "message": (
                                        "Successfully connected to server. "
                                        "Match starting!"
                                    ),
                                },
                            )
                            start_shape_selection()

                    t = threading.Thread(
                        target=handle_client,
                        args=(conn, player_id),
                        daemon=True,
                    )
                    t.start()
                    threads.append(t)

                while not match_done_event.is_set():
                    time.sleep(0.2)

                for t in threads:
                    t.join(timeout=2.0)

                print(
                    "[SERVER] Match cleaned up. "
                    "Returning to WAITING_FOR_PLAYERS."
                )

        except KeyboardInterrupt:
            print("\n[SERVER] Shutting down server gracefully.")
            sys.exit(0)


if __name__ == "__main__":
    main()