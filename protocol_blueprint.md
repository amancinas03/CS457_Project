## Application-Layer Messaging Protocol Blueprint

### Message Transport & Serialization Format
- **Transport Protocol:** TCP
- **Serialization Format:** JSON
- **Framing Mechanism:** Newline-delimited (`\n`) JSON payloads

### Message Schema Definitions

#### Message Types:
1. `CONNECT` (Client -> Server): Request to join the game room.
2. `LOBBY_WAIT` (Server -> Client): Notification that server is waiting for Player 2.
3. `GAME_START` (Server -> Clients): Game initiated, player randomly chosen to go first (e.g. Player X vs Player O).
4. `ROLE` (Client -> Server): After player is chosen to go first, player chooses their shape (Shape X or Shape O)
5. `PLAYER_TURN` (Client -> Server): Player action (e.g., cell coordinates or answer choice).
6. `STATE_UPDATE` (Server -> Clients): Broadcast current game board / state and active player turn.
7. `GAME_OVER` (Server -> Clients): Victory / Draw notification with final scores.
8. `ERROR` (Server -> Client): Invalid move or malformed packet error.
9. `RESTART` (Client -> Server): Initialize game again, assign new starting positions. 
10. `DISCONNECT` (Client -> Server): Player disconnects from the server


#### Example JSON Protocol Schema:
```json
{
  "msg_type": "PLAYER_TURN",
  "player_id": "Player_1",
  "payload": {
    "row": 0,
    "col": 2
  },
  "timestamp": 1727000000
}
{
    "msg_type": "CONNECT",
    "client_host": "server.mancinasponce.edu",
    "client_port": 49012
}
{
    "msg_type": "LOBBY_WAIT",
    "room_id": "rm-1",
    "assigned_player_id": "Player_1",
    "server_host": "server.mancinasponce.edu",
    "message": "Successfully connected to server. Waiting for Player 2..."
}
{
    "msg_type": "GAME_START",
    "board": [["", "", ""],
              ["", "", ""],
              ["", "", ""]
    ],
    "player_go_first": "Player_1",
    "message": "Player_1 goes first. Please select your shape (X or O)"
}
{
    "msg_type": "ROLE",
    "player_id": "Player_1",
    "shape": "X"
}
{
    "msg_type": "STATE_UPDATE",
    "board": [["X", "", ""],
              ["", "", ""],
              ["", "", "O"]
    ],
    "active_player": "Player_2",
    "message": "Player_2, please make your move."
}
{
    "msg_type": "GAME_OVER",
    "results": "Draw",
    "message": "Game ended in a Draw. No points awarded to any player. Rematch?"
}
```
#### Example of Wire Stream
- {"msg_type":"CONNECT","client_host":"server.mancinasponce.edu","client_port": 49012}\n{"msg_type":"LOBBY_WAIT","room_id":"rm-1","assigned_player_id":"Player_1","server_host":"server.mancinasponce.edu","message":"Connected to server. Waiting for Player 2..."}\n
- Each time the receiver encounters a **\n** or **\n\r**, it extracts the completed line, and deserializes that said JSON object. It will continue doing that for each newline it encounters for each messages. For this game, recv() will collect
the messages it receives, then it is the programs job to manually extract the line after encountering a newline. 

---

### Game State Machine (FSM) Design
- **State Transitions:** Detail state flow: `INIT` -> `WAITING_FOR_PLAYERS` -> `ASSIGN_ROLES` -> `GAME_START` -> `PLAYER_TURN` -> `EVALUATE_MOVE` -> `GAME_OVER` -> `CLEANUP`.
