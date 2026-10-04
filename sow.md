# CS 457 Project Statement of Work (SOW) & Protocol Specification Template

**Student Name:** Adrian Mancinas Ponce  
**Date:** 2026-09-15  
**Course:** CS 457 - Computer Networks  
**Target Server Domain:** `server.mancinasponce.edu`  

---

## 1. Game Selection & Scope (Sprint 0)

> Planning is going to be an iterative process through the sprints so you don't have to have all the details now. Focus on big overview concepts. You will be updating the SOW as we plan.
> You have a lot of freedom to choose a game. There are a couple caveats.  

> - It must run in the console. The lab nodes won't be able to handle extensive graphics.
> - It has to be self-contained. You can use a internet-connector to download you code, but because the architecture must run 5 nodes you won't be able to run 
> - You are encouraged to use python, but I'm not going to make it a strict requirement. The instructor and TA's ability to help with C or Rust, etc will be diminished in other languages.

### 1.1 Game Overview
- **Chosen Game:** Tic-Tac-Toe
- **Player Capacity:** 2 Players (Simulated via 2 CML Client nodes)
- **Game Summary:** In Tic-Tac-Toe, the goal of each player is to be able to get three in a row in a 3x3 table with X and O. It is essential for each player to pick the correct space in the table in order to win against their opponent.

### 1.2 Core Game Rules & Win/Draw Conditions
- **Turn Mechanics:** In Tic-Tac-Toe, when both players start playing in the first game, the first person to go will be randomly chosen, and are able to choose a shape (X or O) they want for the rest of the game. When a player wins, the player who've lost will begin their first move the next round.
- **Victory Condition:** A player wins a round if they get 3 Xs or Os in a row or diagonally. After 10 rounds, or however long two players want to go for, a player wins if they got the most amount of points. 
- **Draw/Tie Condition:** if there is a tie, the player who began the round will start first again.

---

## 2. Application-Layer Messaging Protocol Blueprint (Sprint 1 Deliverable)

### 2.1 Message Transport & Serialization Format
- **Transport Protocol:** TCP
- **Serialization Format:** JSON
- **Framing Mechanism:** Newline-delimited (`\n`) JSON payloads

### 2.2 Message Schema Definitions

### Message Types:
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

### 2.3 Game State Machine (FSM) Design (Sprint 1 Deliverable)
- **State Transitions:** Detail state flow: `INIT` -> `WAITING_FOR_PLAYERS` -> `ASSIGN_ROLES` -> `GAME_START` -> `PLAYER_TURN` -> `EVALUATE_MOVE` -> `GAME_OVER` -> `CLEANUP`.

### Connection Termination & Socket Lifecycle Management
- For a graceful application disconnection, like DISCONNECT or tcp fin, the client who wants to quit will send a DISCONNECT message first to the server, to let the opponent know they won by forfeit. After that, the quitting player will do a tcp fin handshake to initiate the disconnection and go back to the lobby.

- To handle TCP EOF 0 Byte rule, after the disconnection has been successfully completed, the player will check if any data will be sent such as TCP FIN. If they receive 0 bytes, or TCP FIN, from "data = socket.recv(1024), then the line "if not data:" will handle it gracefully, let the player know and send the player back to the lobby.

- However, when it comes to handling ConnectionResetError, BrokenPipeError, or TimeoutError exceptions when an opponent leaves abruptly or something else happens, the code will contain the except line to catch all those three errors. With that, it allows the player to know that the Connection was lost abruptly due to three possible things. They will be declared as a winner, and just like TCP EOF, the game will send the player back to the lobby.
---

## 3. Game Behavior & Server Concurrency Architecture (Sprint 2 Deliverable)

### 3.1 Server Concurrency Strategy
- **Architecture Choice:** [Multi-Threading (`threading.Thread`) OR Non-blocking I/O multiplexing (`select.select` / `selectors`)]
- **Synchronization Logic:** Explain how shared game state and client list are thread-safe (e.g. `threading.Lock`) to prevent race conditions during turn processing.

### 3.2 State & Score Synchronization Across Clients
- **Turn Enforcement:** Detail how the server validates active player ID before processing moves and broadcasts updated turn notifications to all clients.
- **Score & Board Synchronization:** Describe how state broadcasts keep client screens synchronized in real time.

---

## 4. Coding & AI Implementation Plan (Sprint 3)

- **Permitted AI Tools:** [e.g., GitHub Copilot, ChatGPT, Claude]
- **AI Prompting & Constraint Strategy:** Explain how you will constrain AI models to generate code (in Python or your chosen language) that adheres strictly to the protocol blueprint and FSM designed in Sprints 1 & 2.
- **Implementation Risk Management:** Detail your plan to leverage past programming experience and manage time to ensure code completion on schedule.

---

## 5. CML Multi-Subnet Topology & Wireshark Deployment Plan (Sprint 4 & 5 Deliverable)

> For now you can use the topology below. We may update this when we get to defining subnets.

### 5.1 Subnet & Router Design
- **Subnet A (Client 1):** `192.168.10.0/24` (Interface `Gi0/1` on Router R1)
- **Subnet B (Client 2):** `192.168.11.0/24` (Interface `Gi0/2` on Router R1)
- **Subnet C (Game Server):** `192.168.20.0/24` (Interface `Gi0/1` on Router R2)
- **Router Backbone:** `10.0.0.0/30` (Interface `Gi0/0` on R1 <-> `Gi0/0` on R2)

### 5.2 DHCP Pools & DNS Configuration Plan
- **Router R1 DHCP Pool 1 (`CLIENT1_POOL`):** Leases `192.168.10.10` - `192.168.10.50`, gateway `192.168.10.1`, DNS `10.0.0.2`.
- **Router R1 DHCP Pool 2 (`CLIENT2_POOL`):** Leases `192.168.11.10` - `192.168.11.50`, gateway `192.168.11.1`, DNS `10.0.0.2`.
- **Router R2 Authoritative DNS:** Configured with `ip dns server` and static host mapping `server.[yourlastname].edu` -> `192.168.20.100`.

### 5.3 Deployment Strategy & Wireshark Trace Capture
- **CML Deployment Strategy:** Deploy `server.py` onto Subnet C node (`192.168.20.100`) behind Router R2, and `client.py` onto Subnet A and Subnet B nodes behind Router R1.
- **Cisco Infrastructure Configuration:** Router R1 DHCP pools (`CLIENT1_POOL`, `CLIENT2_POOL`) and Router R2 authoritative DNS (`ip host server.[lastname].edu 192.168.20.100`).
- **Wireshark Trace Capture Plan:** Capture DHCP DORA exchange (`dhcp_negotiation.pcap`) and DNS query/response resolution (`dns_lookup.pcap`).
