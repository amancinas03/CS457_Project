"""
TCP Tic-Tac-Toe Client (Sprint 3).
Supports DNS hostname resolution with Cisco router diagnostic reporting,
newline-delimited JSON framing, and clean AFK timeout handling.
"""

import argparse
import json
import select
import socket
import sys


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
    """Parse CLI arguments for server hostname/IP and port."""
    parser = argparse.ArgumentParser(
        description="TCP Tic-Tac-Toe Game Client."
    )
    parser.add_argument(
        "-i",
        "--hostname",
        required=True,
        help="Server DNS hostname or IPv4 address.",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=validate_port,
        required=True,
        help="Server TCP port (1024-65535).",
    )
    return parser.parse_args()


def send_json(sock, payload):
    """Serialize dictionary to newline-delimited JSON and send over TCP."""
    data = (json.dumps(payload) + "\n").encode("utf-8")
    sock.sendall(data)


def socket_has_incoming_data(sock):
    """Return True if the server has already sent data (e.g., AFK timeout)."""
    try:
        readable, _, _ = select.select([sock], [], [], 0.0)
        return bool(readable)
    except (ValueError, OSError):
        return True


def render_board(board):
    """Render a clean, human-readable 3x3 CLI board with coordinates."""
    print("\n    0   1   2")
    print("  +---+---+---+")
    for idx, row in enumerate(board):
        print(f"{idx} | {row[0]} | {row[1]} | {row[2]} |")
        print("  +---+---+---+")
    print()


def prompt_shape_choice(sock, player_id):
    """Prompt the starting player to choose X or O unless server timed out."""
    while True:
        choice = input(f"[{player_id}] Choose your shape (X or O): ").strip()
        if socket_has_incoming_data(sock):
            return
        if choice.upper() in ("X", "O"):
            send_json(sock, {"type": "SHAPE_CHOICE", "shape": choice.upper()})
            return
        print("[INVALID] Please enter 'X' or 'O'.")


def prompt_move(sock, player_id):
    """Prompt the active player for a 'row col' move or 'quit'."""
    while True:
        raw = input(
            f"[{player_id}] Enter your move as 'row col' (e.g., 0 2) "
            "or 'quit' to forfeit: "
        ).strip()
        if socket_has_incoming_data(sock):
            return
        if raw.lower() == "quit":
            send_json(sock, {"type": "QUIT"})
            return
        parts = raw.split()
        if len(parts) != 2:
            print("[INVALID] Enter two numbers separated by a space (0 2).")
            continue
        try:
            r, c = int(parts[0]), int(parts[1])
        except ValueError:
            print("[INVALID] Row and column must be integers (0, 1, or 2).")
            continue
        if not (0 <= r <= 2 and 0 <= c <= 2):
            print("[INVALID] Coordinates must be between 0 and 2.")
            continue
        send_json(sock, {"type": "MOVE", "row": r, "col": c})
        return


def prompt_rematch(sock):
    """Prompt the player for a rematch vote ('yes' or 'no')."""
    while True:
        ans = input("Would you like a rematch? (yes/no): ").strip().lower()
        if socket_has_incoming_data(sock):
            return
        if ans in ("yes", "y", "no", "n"):
            vote = "yes" if ans in ("yes", "y") else "no"
            send_json(sock, {"type": "REMATCH", "vote": vote})
            return
        print("[INVALID] Please type 'yes' or 'no'.")


def play_session(server_ip, hostname, port):
    """Connect to the server and run a complete game session."""
    player_id = None
    last_context = None
    buffer = ""

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((server_ip, port))

            while True:
                chunk = sock.recv(1024)
                if not chunk:
                    print(
                        "\n[INFO] Received 0 bytes (TCP FIN / EOF) from "
                        "server. Returning to lobby..."
                    )
                    return

                buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    msg = json.loads(line)
                    mtype = msg.get("type")

                    if mtype == "LOBBY":
                        player_id = msg.get("player_id")
                        print(
                            f"\n[LOBBY] Assigned ID: {player_id} | "
                            f"{msg.get('message')}"
                        )

                    elif mtype == "GAME_START":
                        render_board(msg.get("board"))
                        print(f"[GAME START] {msg.get('message')}")
                        if msg.get("choose_shape"):
                            last_context = "CHOOSE_SHAPE"
                            prompt_shape_choice(sock, player_id)

                    elif mtype == "STATE_UPDATE":
                        render_board(msg.get("board"))
                        scores = msg.get("scores")
                        active = msg.get("active_turn")
                        print(f"[SCORES] {scores} | Active Turn: {active}")
                        print(f"[STATUS] {msg.get('message')}")
                        if active == player_id:
                            last_context = "MOVE"
                            prompt_move(sock, player_id)
                        else:
                            print(
                                f"Waiting for {active} to make a move..."
                            )

                    elif mtype == "ROUND_OVER":
                        render_board(msg.get("board"))
                        print(
                            "================ ROUND OVER ================"
                        )
                        print(f"Round Result : {msg.get('message')}")
                        print(f"Current Score: {msg.get('scores')}")
                        print(f"Match Leader : {msg.get('leader')}")
                        print(
                            "============================================"
                        )
                        last_context = "REMATCH"
                        prompt_rematch(sock)

                    elif mtype == "INFO":
                        print(f"[INFO] {msg.get('message')}")

                    elif mtype == "ERROR":
                        print(f"[SERVER ERROR] {msg.get('message')}")
                        if last_context == "CHOOSE_SHAPE":
                            prompt_shape_choice(sock, player_id)
                        elif last_context == "MOVE":
                            prompt_move(sock, player_id)
                        elif last_context == "REMATCH":
                            prompt_rematch(sock)

                    elif mtype == "GAME_OVER":
                        print(
                            "\n============= FINAL MATCH RESULTS "
                            "============="
                        )
                        print(f"Final Scores : {msg.get('scores')}")
                        print(f"Final Winner : {msg.get('final_winner')}")
                        print(f"Message      : {msg.get('message')}")
                        print(
                            "============================================="
                            "==\n"
                        )
                        return

    except ConnectionRefusedError:
        print(
            f"\n[ERROR] Connection refused by {hostname} "
            f"({server_ip}:{port}). Is the server running?"
        )
    except (ConnectionResetError, BrokenPipeError, OSError) as err:
        print(f"\n[ERROR] Network connection lost: {err}")


def main():
    """Resolve server hostname via DNS and manage lobby entry loop."""
    args = parse_args()

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
            cmd = input(
                "\nPress Enter to join the game lobby "
                "(or type 'exit' to close): "
            ).strip()
            if cmd.lower() == "exit":
                print("Exiting client. Goodbye!")
                break
            play_session(server_ip, args.hostname, args.port)
    except KeyboardInterrupt:
        print("\nExiting client. Goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()