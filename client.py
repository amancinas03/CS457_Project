import argparse
import json
import select
import socket
import sys
import time


def parse_args():
    """Parses and validates CLI arguments for the client (-h, -i, -p)."""
    parser = argparse.ArgumentParser(
        description="Tic-Tac-Toe TCP Game Client"
    )
    parser.add_argument(
        "-i",
        dest="hostname",
        metavar="<server_hostname_or_ip>",
        required=True,
        help=(
            "Server DNS hostname or IP (required; resolved via "
            "socket.gethostbyname())."
        ),
    )
    parser.add_argument(
        "-p",
        dest="port",
        metavar="<port>",
        type=int,
        required=True,
        help="Server port (required; range 1024-65535).",
    )
    args = parser.parse_args()
    if not (1024 <= args.port <= 65535):
        parser.error("Port number (-p) must be in the range 1024-65535.")
    return args


def send_json(sock, data):
    """Serializes dict to JSON with a trailing newline and sends all."""
    payload = (json.dumps(data) + "\n").encode("utf-8")
    sock.sendall(payload)


def render_board(board):
    """Displays the 3x3 Tic-Tac-Toe board in the terminal."""
    print("\n    0   1   2")
    print("  +---+---+---+")
    for r_idx, row in enumerate(board):
        cells = [cell if cell != "" else " " for cell in row]
        print(f"{r_idx} | {cells[0]} | {cells[1]} | {cells[2]} |")
        print("  +---+---+---+")


def compute_final_winner(scores):
    """Determines the final winner with the highest score from scores."""
    p1 = scores.get("player_1", 0)
    p2 = scores.get("player_2", 0)
    if p1 > p2:
        return f"player_1 (Most Points: {p1} to {p2})"
    if p2 > p1:
        return f"player_2 (Most Points: {p2} to {p1})"
    return f"Draw / Tie ({p1} to {p2})"


def print_final_results(scores, message_text, results_override=None):
    """Displays Final Results and Overall Winner before CLEANUP/lobby."""
    winner_str = results_override or compute_final_winner(scores)
    print("\n============= FINAL MATCH RESULTS =============")
    print(f"Final Scores : {scores}")
    print(f"Final Winner : {winner_str}")
    print(f"Message      : {message_text}")
    print("===============================================")


def has_incoming_server_event(sock):
    """
    Uses select() to check if the server already sent an ERROR,
    GAME_OVER (forfeit win), or TCP FIN while this client was waiting at
    an input() prompt. Prevents writing to a closed socket so unread
    server packets are never aborted.
    """
    try:
        readable, _, _ = select.select([sock], [], [], 0)
        return bool(readable)
    except (ValueError, OSError):
        return True


def graceful_disconnect(sock, player_id):
    """
    Sends an application-layer DISCONNECT message first, then initiates
    a TCP FIN handshake (shutdown SHUT_WR) before closing the socket.
    """
    try:
        send_json(
            sock,
            {
                "msg_type": "DISCONNECT",
                "player_id": player_id,
                "timestamp": int(time.time()),
            },
        )
        sock.shutdown(socket.SHUT_WR)
    except (
        ConnectionResetError,
        ConnectionAbortedError,
        BrokenPipeError,
        TimeoutError,
        OSError,
    ):
        pass
    finally:
        try:
            sock.close()
        except OSError:
            pass


def prompt_and_send_move(sock, player_id, latest_scores):
    """Prompts the active player for row/col or 'quit' to forfeit."""
    while True:
        user_input = input(
            f"[{player_id}] Enter your move as 'row col' (e.g., 0 2) "
            "or 'quit' to forfeit: "
        ).strip()

        # If opponent disconnected while typing our move, skip send_json()
        # and let the main recv() loop read the server's GAME_OVER message.
        if has_incoming_server_event(sock):
            return True

        if user_input.lower() in ("quit", "disconnect", "q"):
            other_pid = "player_2" if player_id == "player_1" else "player_1"
            updated_scores = dict(latest_scores)
            updated_scores[other_pid] = updated_scores.get(other_pid, 0) + 1
            print("Initiating graceful forfeit (DISCONNECT + TCP FIN)...")
            overall_str = compute_final_winner(updated_scores)
            print_final_results(
                updated_scores,
                f"You forfeited the match. {other_pid} wins by forfeit! "
                "Returning to lobby...",
                results_override=f"{other_pid} Wins by Forfeit ({overall_str})",
            )
            graceful_disconnect(sock, player_id)
            return False

        parts = user_input.split()
        if len(parts) != 2:
            print(
                "Invalid input format. Please enter two numbers "
                "separated by a space (e.g., 0 2)."
            )
            continue

        try:
            row, col = int(parts[0]), int(parts[1])
        except ValueError:
            print("Coordinates must be integers.")
            continue

        data = {
            "msg_type": "PLAYER_TURN",
            "player_id": player_id,
            "payload": {
                "row": row,
                "col": col,
            },
            "timestamp": int(time.time()),
        }
        send_json(sock, data)
        return True


def play_session(server_ip, hostname, port):
    """Connects to the resolved server IP and runs one full game session."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    last_phase = None
    latest_scores = {"player_1": 0, "player_2": 0}
    final_results_shown = False

    try:
        sock.connect((server_ip, port))
        local_port = sock.getsockname()[1]

        # Send initial CONNECT message
        send_json(
            sock,
            {
                "msg_type": "CONNECT",
                "client_host": hostname,
                "client_port": local_port,
            },
        )

        recv_buffer = ""
        player_id = None
        turn = False

        while True:
            # Inactive player remains in `if not turn: sock.recv(1024)`
            # until the server sends an update.
            if not turn:
                data = sock.recv(1024)
            else:
                data = sock.recv(1024)

            # Handle TCP EOF (0-byte rule)
            if not data:
                if last_phase == "GAME_OVER":
                    if not final_results_shown:
                        print_final_results(
                            latest_scores,
                            "Opponent declined the rematch. "
                            "Match concluded! Returning to lobby...",
                        )
                        final_results_shown = True
                elif last_phase == "GAME_START":
                    print(
                        "\n[ERROR] Opponent disconnected during shape "
                        "selection. Returning to lobby..."
                    )
                else:
                    print(
                        "\n[INFO] Received 0 bytes (TCP FIN / EOF) from "
                        "server. Returning to lobby..."
                    )
                break

            recv_buffer += data.decode("utf-8")

            # Extract each newline-delimited (\n or \r\n) JSON message
            while "\n" in recv_buffer:
                line, recv_buffer = recv_buffer.split("\n", 1)
                line = line.rstrip("\r").strip()
                if not line:
                    continue

                msg = json.loads(line)
                msg_type = msg.get("msg_type")

                if msg_type == "LOBBY_WAIT":
                    if last_phase != "GAME_OVER":
                        last_phase = "LOBBY_WAIT"
                    player_id = msg.get("assigned_player_id", player_id)
                    turn = False
                    print(
                        f"\n[LOBBY] Assigned ID: {player_id} | "
                        f"{msg.get('message')}"
                    )

                elif msg_type == "GAME_START":
                    last_phase = "GAME_START"
                    empty_board = [["", "", ""], ["", "", ""], ["", "", ""]]
                    render_board(msg.get("board", empty_board))
                    print(f"\n[GAME START] {msg.get('message')}")
                    if msg.get("player_go_first") == player_id:
                        turn = True
                        shape = (
                            input(
                                f"[{player_id}] Choose your shape (X or O): "
                            )
                            .strip()
                            .upper()
                        )

                        # If the waiting opponent disconnected while choosing
                        # a shape, skip send_json() to read the ERROR packet.
                        if has_incoming_server_event(sock):
                            turn = False
                            continue

                        send_json(
                            sock,
                            {
                                "msg_type": "ROLE",
                                "player_id": player_id,
                                "shape": shape,
                            },
                        )
                        turn = False
                    else:
                        turn = False

                elif msg_type == "STATE_UPDATE":
                    last_phase = "PLAYER_TURN"
                    render_board(msg.get("board", []))
                    if "scores" in msg:
                        latest_scores = msg.get("scores")
                    active = msg.get("active_player")
                    turn = msg.get("turn", active == player_id)
                    print(
                        f"[SCORES] {latest_scores} | Active Turn: {active}"
                    )
                    print(f"[STATUS] {msg.get('message')}")

                    if turn:
                        keep_playing = prompt_and_send_move(
                            sock, player_id, latest_scores
                        )
                        if not keep_playing:
                            final_results_shown = True
                            return
                        turn = False

                elif msg_type == "ERROR":
                    err_text = msg.get("message", "Unknown error")
                    # If opponent declined rematch while in GAME_OVER,
                    # display final winner before returning to lobby.
                    if "declined" in err_text:
                        if not final_results_shown:
                            print_final_results(latest_scores, err_text)
                            final_results_shown = True
                        return
                    print(f"\n[ERROR] {err_text}")
                    if "Returning to lobby" in err_text:
                        return
                    # If active player made an invalid move on their turn,
                    # re-prompt immediately.
                    if (
                        last_phase == "PLAYER_TURN"
                        and "Wait for your turn" not in err_text
                    ):
                        keep_playing = prompt_and_send_move(
                            sock, player_id, latest_scores
                        )
                        if not keep_playing:
                            final_results_shown = True
                            return
                        turn = False

                elif msg_type == "GAME_OVER":
                    last_phase = "GAME_OVER"
                    turn = False
                    if "scores" in msg:
                        latest_scores = msg.get("scores")

                    # If this is the final match summary (forfeit or declined
                    # rematch), display Final Winner and return to lobby.
                    if (
                        msg.get("final")
                        or "Forfeit" in str(msg.get("results", ""))
                        or "lost" in str(msg.get("message", ""))
                    ):
                        if not final_results_shown:
                            print_final_results(
                                latest_scores,
                                msg.get("message"),
                                results_override=compute_final_winner(
                                    latest_scores
                                ),
                            )
                            final_results_shown = True
                        return

                    # Round over summary
                    print("\n================ ROUND OVER ================")
                    print(f"Round Result   : {msg.get('results')}")
                    print(f"Current Scores : {latest_scores}")
                    print(
                        "Current Leader : "
                        f"{compute_final_winner(latest_scores)}"
                    )
                    print(f"Message        : {msg.get('message')}")
                    print("============================================")

                    choice = (
                        input("Would you like a rematch? (yes/no): ")
                        .strip()
                        .lower()
                    )

                    # If the faster player already hit 'no' (or disconnected)
                    # while at the prompt, skip send_json() and let recv()
                    # process the server's final GAME_OVER summary.
                    if has_incoming_server_event(sock):
                        continue

                    if choice in ("yes", "y"):
                        send_json(
                            sock,
                            {
                                "msg_type": "RESTART",
                                "player_id": player_id,
                            },
                        )
                    else:
                        print_final_results(
                            latest_scores,
                            f"{player_id} declined the rematch. "
                            "Match concluded! Returning to lobby...",
                        )
                        final_results_shown = True
                        graceful_disconnect(sock, player_id)
                        return

    except (
        ConnectionResetError,
        ConnectionAbortedError,
        BrokenPipeError,
        TimeoutError,
    ) as exc:
        if last_phase == "GAME_OVER":
            if not final_results_shown:
                print_final_results(
                    latest_scores,
                    "Opponent declined the rematch. "
                    "Match concluded! Returning to lobby...",
                )
                final_results_shown = True
        elif last_phase in (None, "LOBBY_WAIT", "GAME_START"):
            print(
                f"\n[ERROR] Opponent disconnected during setup "
                f"({type(exc).__name__}). Returning to lobby..."
            )
        else:
            if player_id in latest_scores:
                latest_scores[player_id] = (
                    latest_scores.get(player_id, 0) + 1
                )
            overall_str = compute_final_winner(latest_scores)
            print_final_results(
                latest_scores,
                f"Connection terminated abruptly ({type(exc).__name__}). "
                "You are declared the winner! Returning to lobby...",
                results_override=(
                    f"{player_id} Wins by Forfeit ({overall_str})"
                ),
            )
            final_results_shown = True
    except KeyboardInterrupt:
        print("\n[INFO] Disconnecting from current match...")
    except ConnectionRefusedError:
        print(
            f"\n[ERROR] Connection refused by {hostname} "
            f"({server_ip}:{port}). Is the server running?"
        )
    finally:
        try:
            sock.close()
        except OSError:
            pass


def main():
    """Resolves the server hostname via DNS and starts the lobby loop."""
    args = parse_args()

    # Section 2.2: Mandatory Graceful DNS Resolution Exception Handling
    try:
        server_ip = socket.gethostbyname(args.hostname)
    except socket.gaierror:
        print(f"[ERROR] Unable to resolve DNS hostname '{args.hostname}'.")
        print(
            "Please check your Cisco router DNS configuration "
            "('ip dns server' / 'ip host') or verify domain spelling."
        )
        sys.exit(1)

    print(
        f"=== Tic-Tac-Toe Client "
        f"(Target: {args.hostname} [{server_ip}:{args.port}]) ==="
    )
    try:
        while True:
            cmd = (
                input(
                    "\nPress Enter to join the game lobby "
                    "(or type 'exit' to close): "
                )
                .strip()
                .lower()
            )
            if cmd == "exit":
                break
            play_session(server_ip, args.hostname, args.port)
    except KeyboardInterrupt:
        print("\nExiting Tic-Tac-Toe Client.")


if __name__ == "__main__":
    main()
