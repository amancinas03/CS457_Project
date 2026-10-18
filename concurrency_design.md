# Server Concurrency Strategy
## **Architecture Choice:** Multi-Threading (`threading.Thread`)
- The server will utilize a multi-threaded threading.Thread to ensure that each connected client are automatically binded to a thread from the server after a successful connection, creating a multi-0threaded connection. The server will normally initialize a TCP socket with `s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)` and `s.bind((IP_ADDR, PORT))`.
Since the game of tic-tac-toe only allow a maximum of two players, the server will only run a loop twice to connect both players to the server for the game.
### **Connection and Registration Phase:**
- For each iteration, the server will first use the listen function `s.listen()` to wait for a player to connect. It will then utilize the `threading.Thread(target=handle_client, args=(client_socket, client_address, player_id))` function after `client_socket, client_address = socket.accept()`. Each player will be assigned with a unique ID assigned by the server for example, `player_id = "player_1"` and `player_id = "player_2"`. The server will start the thread, with an example of the function `thread.start()`. Each connected player will be added to a list to keep track of who is connected with their info.
### **Active Game Loop Serive:**
- Before the game begins, the server will choose randomly on who gets to go first with a function `random.choice(players)`. The player that gets to go first will choose their shape. The server will also do a verification step to ensure that the client did not choose an invalid shape.
- During the game, both players will utilize the newline delimitator for JSON. Active player will be sending packets to the server, while the inactive player will be remaining in `socket.recv(1024)` until the server updates the board, and swapping the players turn.
### **Socket Teardown and Graceful Disconnection:**
- When the game concludes and both players did not agree to a rematch, the game will notify the players that the game has concluded, shutdown the socket first, then clean up the game, and finally close the sockets of each player for them to go back to the lobby. But in certain scenario where a player disconnects suddenly and the server only receiving 0 bytes from the disconnected player. The server will automatically conclude the game, make the remaining player the winner, and do the same process of shutting down and closing gracefully to the only connected player.
### **Extra Note:**
- There is a possibility of a player disconnecting during the assigning phase as well. The server would also be listening to any 0 byte that may come from the user who've disconnected suddenly. If that's detected, the server will notify the connected player, shutdown the socket, clean up the game, and close the socket to allow them to go back to the lobby.
## **Synchronization Logic:** 
- After binding the connections of both players, threading.Lock from here on out to prevent any data corruption or prohibited access from the outside that could break the game.
- The server will be updating variables in the shared space of the shape each player will now have, releases that lock, such as lock.release(), and then send a state update.
  After the assigning process has been complete the game will begin:
1. The first player will have their turn = True, indicating that they're an active player. The inactive opponent will have their turn = False. The inactive play will in `if not turn: socket.recv(1024)` section, until the server sends the update.
3. The active player will make their choice in the board, such as row = 0, col = 2. The active player will then convert their data into a JSON payload/message with `json.dumps(data).encode("utf-8"`), with data containing: *data = {}, data["player_id"] = id, data["row"] = 0, and data["col"] = 2*.
4. The player will send it into the socket created to the server with the function `socket.sendall(data)`.
5. The server will first verify that the message received is the currently active player. It will then use the function `with game_lock:` after `thread.Lock()` to ensure no one enters the shared resource and prevent any attempts of cheating or multiple users being in the shared resource space. This function will automatically acquire and release the lock instead of manually stating it every time.
7. It will then verify to see if the space is claimed or not. It will add the shape of the player to the empty space if no one has claimed it first after the verification. Finally, the server swaps the active players and send a STATE_UPDATE to the players after leaving the shared resource space. For example:
```python
validate_player_id(player_id)
with game_lock:
  validate_empty_space(row, col)
  board[row][col] = player_shape

  if check_winner(board):
    game_state = "CONCLUDED"
    points[player_id] += 1
    break
  if draw():
    game_state = "CONCLUDED"
    break
  if active_player == "player_1":
    active_player = "player_2"
  else:
    active_player = "player_1"
```
8. These actions will repeat until the server finds a winning 3 in a row or draw.
### **Extra Note:**
- When the server gathered the connected players into a list to ensure how many players are connected and to send the messages to. By only letting it used by the server in the shared resource, it prevents any other players from manipulating the list, which can cause failure, or allow any player to cheat. Similar to how only the game board is only being mutated by the server during the lock acquisition phase, players' point are also kept in the shared resource. By having the players' points in the shared resource, this prevents any sort of cheating or point manipulation by the client, but also allow the server to accurately track how many points each client has.
