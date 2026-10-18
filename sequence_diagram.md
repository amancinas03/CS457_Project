## State & Score Synchronization Across Clients
### **Turn Enforcement:**
- Each player will contain a unique ID assigned by the server itself instead of the user, to identify the first and second player (ex. player1) instead of by name.
  The server will keep track of which ID is active at the moment. The active player will make their move, and then send their ID alongside their move to the server. The server will then compare the ID sent by the player with the ID it is currently tracking (if curr_player_id == player.player_id).
  If true, then the server will validate the move (if validateselection(row, col)). If successful, the server will record the move, and then switch to the next player.
### **Score & Board Synchronization:**
- Neither clients will contain the actual board, the server will. The server will hold the most up to date board and after each time a move has been made, it will display the board to all players when loading the json with json.loads() in a STATE_UPDATE each times.
  Since this game will utilize the JSON framing structure, the data will come as a JSON string. 
### Turn Diagram:

```mermaid
sequenceDiagram
    autonumber
    actor Player1 as Player 1 (Player X)
    participant Server as Game Server
    actor Player2 as Player 2 (Player O)

    Player1->>Server: MOVE (row: 0, col: 2)
    Note over Server: Server validates: Is it Player 1's turn?<br>Is cell (0,2) empty?
    alt Invalid / Out of Turn Move
        Server-->>Player1: ERROR ('Move not valid' or 'Wait for your turn')
    else Valid Move
        Note over Server: Update Board & Swap Active Player to Player 2
        Server-->>Player1: STATE_UPDATE (Board, Turn: Player 2, Turn_Status: False)
        Server-->>Player2: STATE_UPDATE (Board, Turn: Player 2, Turn_Status: True)
    end

    Player2->>Server: MOVE (row: 2, col: 0)
    Note over Server: Server validates: Is it Player 2's turn?<br>Is cell (2,0) empty?
    alt Invalid / Out of Turn Move
        Server-->>Player2: ERROR ('Move not valid' or 'Wait for your turn')
    else Valid Move
        Note over Server: Update Board & Swap Active Player to Player 1
        Server-->>Player1: STATE_UPDATE (Board, Turn: Player 1, Turn_Status: True)
        Server-->>Player2: STATE_UPDATE (Board, Turn: Player 1, Turn_Status: False)
    end
```
