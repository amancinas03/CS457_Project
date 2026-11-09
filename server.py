import argparse
import json
import random
import socket
import threading
import time

# Default protocol constants
IP_ADDR = "0.0.0.0"
SERVER_HOSTNAME_LABEL = "server.mancinasponce.edu"
ROOM_ID = "rm-1"
TURN_TIMEOUT = 30.0  # 30-second disconnect/forfeit timeout per FSM diagram

# Shared resources protected by game_lock
game_lock = threading.Lock()
clients = {}          # {"player_1": socket, "player_2": socket}
client_buffers = {}   # {"player_1": "", "player_2": ""}
points = {"player_1": 0, "player_2": 0}
player_shapes = {}    # {"player_1": "X", "player_2": "O"}
rematch_votes = set()

board = [["", "", ""], ["", "", ""], ["", "", ""]]
game_state = "INIT"
active_player = None
player_go_first = None
last_loser = None

# Event used to coordinate lobby resets when a match concludes
match_done_event = threading.Event()


def parse_args():
    """Parses CLI arguments for the server (-h, -p)."""
    parser = argparse.ArgumentParser(
        description="Tic-Tac-Toe TCP Game Server"
    )
    parser.add_argument(
        "-p",
        dest="port",
        type=int,
        required=True,
        help="Listening port (required; binds to 0.0.0.0)."
    )
    return parser.parse_args()


def get_overall_winner_text(scores_dict):
    """Determines the overall winner based on whoever has the most points."""
    p1 = scores_dict.get("player_1", 0)
    p2 = scores_dict.get("player_2", 0)
    if p1 > p2:
        return f"player_1 Wins Overall ({p1} to {p2})"
    if p2 > p1:
        return f"player_2 Wins Overall ({p2} to {p1})"
    return f"Match Tied ({p1} to {p2})"


def send_json(sock, payload):
    """Serializes dictionary to JSON and appends a newline delimiter (\\n)."""
    raw_msg = json.dumps(payload) + "\n"
    sock.sendall(raw_msg.encode("utf-8"))


def broadcast_json(payload):
    """Sends a single JSON message to all currently connected players."""
    for _, sock in list(clients.items()):
        try:
            send_json(sock, payload)
        except (
            ConnectionResetError,
            ConnectionAbortedError,
            BrokenPipeError,
            TimeoutError,
            OSError,
        ):
            pass


def send_state_update(message_text=None):
    """
    Sends personalized STATE_UPDATE to each player matching the sequence
    diagram: Board, Turn (active_player), Turn Status (turn: True/False),
    and Scores.
    """
    for pid, sock in list(clients.items()):
        is_turn = (game_state == "PLAYER_TURN") and (pid == active_player)
        msg = message_text or (
            f"{active_player}, please make your move."
            if is_turn
            else f"Waiting for {active_player} to make a move..."
        )
        payload = {
            "msg_type": "STATE_UPDATE",
            "board": board,
            "active_player": active_player,
            "turn": is_turn,
            "scores": points,
            "message": msg,
            "timestamp": int(time.time()),
        }
        try:
            send_json(sock, payload)
        except (
            ConnectionResetError,
            ConnectionAbortedError,
            BrokenPipeError,
            TimeoutError,
            OSError,
        ):
            pass


def recv_json_lines(player_id, sock):
    """
    Reads from TCP stream and manually extracts newline-delimited
    (\\n or \\r\\n) JSON messages. Returns a list of parsed dicts, or
    None on 0-byte EOF.
    """
    data = sock.recv(1024)
    if not data:
        return None  # TCP EOF (0 bytes)

    client_buffers[player_id] += data.decode("utf-8")
    messages = []

    while "\n" in client_buffers[player_id]:
        line, client_buffers[player_id] = (
            client_buffers[player_id].split("\n", 1)
        )
        line = line.rstrip("\r").strip()
        if line:
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                send_json(
                    sock,
                    {
                        "msg_type": "ERROR",
                        "message": "ERROR: Malformed JSON packet.",
                    },
                )
    return messages


def validate_player_id(player_id):
    """Checks if the player making the move is the active player."""
    return player_id == active_player


def validate_empty_space(row, col):
    """Validates board boundaries and checks that the target cell is empty."""
    if not isinstance(row, int) or not isinstance(col, int):
        return False
    if row < 0 or row > 2 or col < 0 or col > 2:
        return False
    return board[row][col] == ""


def check_winner(b):
    """Checks rows, columns, and diagonals for a winning 3-in-a-row."""
    lines = [
        # Rows
        [b[0][0], b[0][1], b[0][2]],
        [b[1][0], b[1][1], b[1][2]],
        [b[2][0], b[2][1], b[2][2]],
        # Columns
        [b[0][0], b[1][0], b[2][0]],
        [b[0][1], b[1][1], b[2][1]],
        [b[0][2], b[1][2], b[2][2]],
        # Diagonals
        [b[0][0], b[1][1], b[2][2]],
        [b[0][2], b[1][1], b[2][0]],
    ]
    for line in lines:
        if line[0] != "" and line[0] == line[1] == line[2]:
            return True
    return False


def draw(b):
    """Returns True if all cells are filled and no winner exists."""
    return all(cell != "" for row in b for cell in row)


def reset_board():
    """Resets the 3x3 board for a new game."""
    global board
    board = [["", "", ""], ["", "", ""], ["", "", ""]]


def handle_disconnect(
    disconnected_pid,
    reason="abruptly disconnected",
    graceful_forfeit=False,
):
    """
    Handles sudden disconnections (EOF, ConnectionResetError,
    BrokenPipeError, TimeoutError) or graceful DISCONNECT messages across
    all FSM phases, displaying the final winner before CLEANUP.
    """
    global game_state
    with game_lock:
        if game_state == "CLEANUP":
            return

        other_pid = (
            "player_2" if disconnected_pid == "player_1" else "player_1"
        )
        other_sock = clients.get(other_pid)
        disc_sock = clients.get(disconnected_pid)

        # 1. Disconnect during setup/shape assignment phase
        if game_state in (
            "WAITING_FOR_PLAYERS",
            "ASSIGN_ROLES",
            "GAME_START",
        ):
            game_state = "CLEANUP"
            if other_sock:
                try:
                    send_json(
                        other_sock,
                        {
                            "msg_type": "ERROR",
                            "message": (
                                f"{disconnected_pid} disconnected during "
                                f"setup ({reason}). Returning to lobby."
                            ),
                        },
                    )
                except OSError:
                    pass

        # 2. Disconnect or forfeit during active gameplay
        elif game_state in ("PLAYER_TURN", "EVALUATE_MOVE"):
            game_state = "GAME_OVER"
            if other_pid in points:
                points[other_pid] += 1
            overall_winner = get_overall_winner_text(points)
            if other_sock:
                try:
                    if graceful_forfeit:
                        forfeit_msg = (
                            f"{disconnected_pid} forfeited the game. "
                            f"{other_pid} wins by forfeit! "
                            f"Final Winner: {overall_winner}. "
                            "Returning to lobby."
                        )
                    else:
                        forfeit_msg = (
                            f"Connection to {disconnected_pid} lost "
                            f"({reason}). {other_pid} wins automatically! "
                            f"Final Winner: {overall_winner}. "
                            "Returning to lobby."
                        )
                    send_json(
                        other_sock,
                        {
                            "msg_type": "GAME_OVER",
                            "final": True,
                            "results": (
                                f"{other_pid} Wins by Forfeit | "
                                f"{overall_winner}"
                            ),
                            "scores": points,
                            "message": forfeit_msg,
                        },
                    )
                except OSError:
                    pass
            game_state = "CLEANUP"

        # 3. Disconnect during GAME_OVER (player declined rematch)
        elif game_state == "GAME_OVER":
            game_state = "CLEANUP"
            overall_winner = get_overall_winner_text(points)
            final_payload = {
                "msg_type": "GAME_OVER",
                "final": True,
                "results": overall_winner,
                "scores": points,
                "message": (
                    f"{disconnected_pid} declined the rematch. "
                    f"Match concluded! Final Winner: {overall_winner}. "
                    "Returning to lobby."
                ),
            }
            for target_sock in (other_sock, disc_sock):
                if target_sock:
                    try:
                        send_json(target_sock, final_payload)
                    except OSError:
                        pass

        else:
            game_state = "CLEANUP"

        cleanup_session_locked()


def cleanup_session_locked():
    """
    Half-closes write side (TCP FIN) first so the remaining client can read
    the final ERROR or GAME_OVER packet without receiving a TCP RST, then
    closes all sockets.
    """
    sockets_to_close = list(clients.values())
    for sock in sockets_to_close:
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass

    # Brief pause to allow final packet delivery before closing descriptor
    time.sleep(0.15)

    for sock in sockets_to_close:
        try:
            sock.close()
        except OSError:
            pass

    clients.clear()
    client_buffers.clear()
    player_shapes.clear()
    rematch_votes.clear()
    reset_board()
    match_done_event.set()


def start_assignment_phase():
    """Transitions from WAITING_FOR_PLAYERS -> ASSIGN_ROLES -> GAME_START."""
    global game_state, player_go_first, active_player
    with game_lock:
        game_state = "ASSIGN_ROLES"
        reset_board()
        player_shapes.clear()
        rematch_votes.clear()

        # On rematch after a win, losing player goes first; else random
        if last_loser in ("player_1", "player_2"):
            player_go_first = last_loser
        else:
            player_go_first = random.choice(list(clients.keys()))

        active_player = player_go_first
        game_state = "GAME_START"

        for pid, sock in list(clients.items()):
            if pid == player_go_first:
                msg = (
                    f"{player_go_first} goes first. "
                    "Please select your shape (X or O)"
                )
            else:
                msg = (
                    f"{player_go_first} goes first and is selecting "
                    "their shape (X or O). Please wait..."
                )
            send_json(
                sock,
                {
                    "msg_type": "GAME_START",
                    "board": board,
                    "player_go_first": player_go_first,
                    "message": msg,
                },
            )


def process_message(player_id, msg):
    """Processes a single deserialized JSON message according to the FSM."""
    global game_state, active_player, last_loser

    msg_type = msg.get("msg_type")
    sock = clients.get(player_id)
    if not sock:
        return

    # 1. CONNECT message
    if msg_type == "CONNECT":
        with game_lock:
            host_label = msg.get("client_host", SERVER_HOSTNAME_LABEL)
            if len(clients) < 2:
                wait_msg = (
                    "Successfully connected to server. "
                    "Waiting for Player 2..."
                )
            else:
                wait_msg = "Both players connected. Initializing game..."

            send_json(
                sock,
                {
                    "msg_type": "LOBBY_WAIT",
                    "room_id": ROOM_ID,
                    "assigned_player_id": player_id,
                    "server_host": host_label,
                    "message": wait_msg,
                },
            )
        return

    # 2. DISCONNECT message (forfeit in gameplay or decline in GAME_OVER)
    if msg_type == "DISCONNECT":
        handle_disconnect(
            player_id,
            reason="client sent DISCONNECT",
            graceful_forfeit=True,
        )
        return

    # 3. ROLE selection during GAME_START
    if msg_type == "ROLE":
        with game_lock:
            if game_state != "GAME_START":
                send_json(
                    sock,
                    {
                        "msg_type": "ERROR",
                        "message": (
                            "ERROR: Role selection is not currently active."
                        ),
                    },
                )
                return

            if player_id != player_go_first:
                send_json(
                    sock,
                    {
                        "msg_type": "ERROR",
                        "message": (
                            "ERROR: Wait for your turn to select a shape."
                        ),
                    },
                )
                return

            chosen_shape = str(msg.get("shape", "")).strip().upper()
            if chosen_shape not in ("X", "O"):
                send_json(
                    sock,
                    {
                        "msg_type": "ERROR",
                        "message": (
                            "ERROR: Invalid shape choice. "
                            "Please choose 'X' or 'O'."
                        ),
                    },
                )
                send_json(
                    sock,
                    {
                        "msg_type": "GAME_START",
                        "board": board,
                        "player_go_first": player_go_first,
                        "message": (
                            f"{player_go_first} goes first. "
                            "Please select your shape (X or O)"
                        ),
                    },
                )
                return

            other_pid = "player_2" if player_id == "player_1" else "player_1"
            other_shape = "O" if chosen_shape == "X" else "X"
            player_shapes[player_id] = chosen_shape
            player_shapes[other_pid] = other_shape

            game_state = "PLAYER_TURN"
            active_player = player_go_first

            send_state_update(
                f"Roles assigned: {player_id} is {chosen_shape}, "
                f"{other_pid} is {other_shape}. "
                f"{active_player}, please make your move."
            )
        return

    # 4. PLAYER_TURN (or MOVE per sequence diagram)
    if msg_type in ("PLAYER_TURN", "MOVE"):
        with game_lock:
            if game_state != "PLAYER_TURN":
                send_json(
                    sock,
                    {
                        "msg_type": "ERROR",
                        "message": (
                            "ERROR: Game is not currently in the "
                            "PLAYER_TURN state."
                        ),
                    },
                )
                return

            game_state = "EVALUATE_MOVE"

            sent_pid = msg.get("player_id", player_id)
            if (
                not validate_player_id(sent_pid)
                or not validate_player_id(player_id)
            ):
                game_state = "PLAYER_TURN"
                send_json(
                    sock,
                    {
                        "msg_type": "ERROR",
                        "message": "Wait for your turn",
                    },
                )
                return

            payload = msg.get("payload", {})
            row = payload.get("row", msg.get("row"))
            col = payload.get("col", msg.get("col"))

            if not validate_empty_space(row, col):
                game_state = "PLAYER_TURN"
                send_json(
                    sock,
                    {
                        "msg_type": "ERROR",
                        "message": "Move not valid, please try again",
                    },
                )
                return

            # Record valid move on the shared board
            board[row][col] = player_shapes[player_id]

            # Evaluate win or draw
            if check_winner(board):
                game_state = "GAME_OVER"
                points[player_id] += 1
                last_loser = (
                    "player_2" if player_id == "player_1" else "player_1"
                )
                active_player = None
                leader_text = get_overall_winner_text(points)
                p_shape = player_shapes[player_id]
                send_state_update(
                    f"{player_id} ({p_shape}) placed at "
                    f"({row}, {col}) and won!"
                )
                broadcast_json(
                    {
                        "msg_type": "GAME_OVER",
                        "final": False,
                        "results": (
                            f"{player_id} Wins Round! "
                            f"(Leader: {leader_text})"
                        ),
                        "scores": points,
                        "message": (
                            f"{player_id} won the round! "
                            f"Scores: {points}. Rematch? (yes/no)"
                        ),
                    }
                )
                return

            if draw(board):
                game_state = "GAME_OVER"
                last_loser = None
                active_player = None
                leader_text = get_overall_winner_text(points)
                send_state_update("Board is full!")
                broadcast_json(
                    {
                        "msg_type": "GAME_OVER",
                        "final": False,
                        "results": f"Draw (Leader: {leader_text})",
                        "scores": points,
                        "message": (
                            "Game ended in a Draw. No points awarded "
                            "to any player. Rematch? (yes/no)"
                        ),
                    }
                )
                return

            # Swap active player and return to PLAYER_TURN
            if active_player == "player_1":
                active_player = "player_2"
            else:
                active_player = "player_1"

            game_state = "PLAYER_TURN"
            send_state_update()
        return

    # 5. RESTART message (Rematch voting in GAME_OVER state)
    if msg_type == "RESTART":
        need_restart = False
        with game_lock:
            if game_state != "GAME_OVER":
                overall_winner = get_overall_winner_text(points)
                send_json(
                    sock,
                    {
                        "msg_type": "GAME_OVER",
                        "final": True,
                        "results": overall_winner,
                        "scores": points,
                        "message": (
                            "Opponent declined the rematch. "
                            f"Final Winner: {overall_winner}. "
                            "Returning to lobby."
                        ),
                    },
                )
                return

            rematch_votes.add(player_id)
            if len(rematch_votes) < 2:
                send_json(
                    sock,
                    {
                        "msg_type": "LOBBY_WAIT",
                        "room_id": ROOM_ID,
                        "assigned_player_id": player_id,
                        "server_host": SERVER_HOSTNAME_LABEL,
                        "message": (
                            "Rematch accepted. "
                            "Waiting for opponent's decision..."
                        ),
                    },
                )
            else:
                need_restart = True

        if need_restart:
            start_assignment_phase()
        return

    # Unknown message type
    send_json(
        sock,
        {
            "msg_type": "ERROR",
            "message": f"ERROR: Unrecognized msg_type '{msg_type}'.",
        },
    )


def handle_client(client_socket, client_address, player_id):
    """Thread worker bound to a single connected player."""
    client_socket.settimeout(TURN_TIMEOUT)
    try:
        while not match_done_event.is_set():
            try:
                messages = recv_json_lines(player_id, client_socket)
            except TimeoutError:
                # If waiting for second player in lobby, keep waiting
                with game_lock:
                    if game_state == "WAITING_FOR_PLAYERS":
                        continue
                print(
                    f"[SERVER] {player_id} timed out after {TURN_TIMEOUT}s."
                )
                handle_disconnect(
                    player_id, reason="TimeoutError (30s inactivity)"
                )
                break

            if messages is None:
                # 0-byte TCP FIN / EOF detected
                print(
                    f"[SERVER] 0-byte EOF received from {player_id} "
                    f"({client_address})."
                )
                handle_disconnect(player_id, reason="TCP EOF (0 bytes)")
                break

            for msg in messages:
                process_message(player_id, msg)
                if match_done_event.is_set():
                    break

    except (
        ConnectionResetError,
        ConnectionAbortedError,
        BrokenPipeError,
        TimeoutError,
    ) as exc:
        print(
            f"[SERVER] Abrupt connection error from {player_id}: "
            f"{type(exc).__name__}"
        )
        handle_disconnect(player_id, reason=type(exc).__name__)
    except OSError:
        pass


def main():
    """Initializes the TCP listener and runs the lobby accept loop."""
    global game_state, points, last_loser

    args = parse_args()
    port = args.port

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((IP_ADDR, port))
    s.listen(2)
    print(f"[SERVER] Tic-Tac-Toe Server listening on {IP_ADDR}:{port}...")

    try:
        while True:
            # Transition: INIT / CLEANUP -> WAITING_FOR_PLAYERS
            with game_lock:
                game_state = "WAITING_FOR_PLAYERS"
                points = {"player_1": 0, "player_2": 0}
                last_loser = None
                match_done_event.clear()

            print(
                "\n[SERVER] State: WAITING_FOR_PLAYERS "
                "(Waiting for 2 players to connect...)"
            )

            # Run connection loop twice to connect both players
            while True:
                with game_lock:
                    if len(clients) >= 2:
                        break
                    assigned_id = (
                        "player_1"
                        if "player_1" not in clients
                        else "player_2"
                    )

                client_socket, client_address = s.accept()
                print(
                    f"[SERVER] Accepted connection from {client_address} "
                    f"as {assigned_id}"
                )

                with game_lock:
                    clients[assigned_id] = client_socket
                    client_buffers[assigned_id] = ""

                thread = threading.Thread(
                    target=handle_client,
                    args=(client_socket, client_address, assigned_id),
                    daemon=True,
                )
                thread.start()

            # Allow initial CONNECT packets to finish before GAME_START
            time.sleep(0.2)
            with game_lock:
                both_still_connected = len(clients) == 2

            if both_still_connected:
                start_assignment_phase()
                match_done_event.wait()
                print(
                    "[SERVER] Match cleaned up. "
                    "Returning to WAITING_FOR_PLAYERS."
                )

    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down server...")
    finally:
        with game_lock:
            cleanup_session_locked()
        s.close()


if __name__ == "__main__":
    main()