# Server Concurrency Strategy
## **Architecture Choice:** Multi-Threading (`threading.Thread`)
- The server will utilize a multi-threaded threading.Thread to ensure that each connected client is automatically bound to a thread from the server after a successful connection, creating a multi-threaded connection. The server will normally initialize a TCP socket with `s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)` and `s.bind((IP_ADDR, PORT))`.
Since the game of tic-tac-toe only allows a maximum of two players, the server will only run a loop twice to connect both players to the server for the game.
### **Connection and Registration Phase:**
- For each iteration, the server will first use the listen function `s.listen()` to wait for a player to connect. It will then utilize the `threading.Thread(target=handle_client, args=(client_socket, client_address, player_id))` function after `client_socket, client_address = socket.accept()`. Each player will be assigned with a unique ID assigned by the server for example, `player_id = "player_1"` and `player_id = "player_2"`. The server will start the thread, with an example of the function `thread.start()`. Each connected player will be added to a list to keep track of who is connected with their info.
### **Active Game Loop Service:**
- Before the game begins, the server will choose randomly who gets to go first with a function `random.choice(players)`. The player that gets to go first will choose their shape. The server will also do a verification step to ensure that the client did not choose an invalid shape.
- During the game, both players will utilize the newline delimiter for JSON:
1. The first player will have their turn = True, indicating that they're an active player. The inactive opponent will have their turn = False. The inactive player will remain in `if not turn: socket.recv(1024)` section, until the server sends the update.
3. The active player will make their choice in the board, such as row = 0, col = 2. The active player will then convert their data into a JSON payload/message with `json.dumps(data).encode("utf-8")`, with data containing: *data = {}, data["player_id"] = id, data["row"] = 0, and data["col"] = 2*.
4. The player will send it into the socket created to the server with the function `socket.sendall(data)`.
5. The server will validate the message first before making changes and swapping the active player.
6. The server will then send the state update to the players and allow the next player to make a selection.
### **Socket Teardown and Graceful Disconnection:**
- When the game concludes and both players did not agree to a rematch, the game will notify the players that the game has concluded, shut down the socket first, then clean up the game, and finally close the sockets of each player for them to go back to the lobby. There are scenarios where a player disconnects suddenly, and the server receives 0 bytes from the disconnected player. The server will automatically conclude the game, make the remaining player the winner, and do the same process of shutting down and closing gracefully to the only connected player.
### **Extra Note:**
- There is a possibility of a player disconnecting during the assigning phase as well. The server will listen for 0 bytes that may come from a user who has disconnected suddenly. If it is detected, the server will notify the connected player, shut down the socket, clean up the game, and close the socket to allow them to go back to the lobby.
## **Synchronization Logic:** 
- After binding the connections of both players, threading.Lock from here on out to prevent  data corruption or prohibited access from the outside that could break the game.
- During gameplay, the server will have necessary functions and locks so that no one else enters the shared resource space, except for the server:
1. When the server receives a message from an active player, it will initializes `game_lock = thread.Lock()`, and then use `with game_lock:` to ensure no one enters the shared resource and prevent any attempts of cheating or multiple users being in the shared resource space. This function will automatically acquire and release the lock due to how `with game_lock:` works.
2. First, it will verify that the message received is the currently active player, then verifies to see if the space is claimed or not. It will add the shape of the player to the empty space if no one has claimed it first after the verification. Finally, the server swaps the active players and sends a STATE_UPDATE to the players after leaving the shared resource space
3. These actions will repeat until the server finds a winning 3 in a row or draw.
- Here's an example of how the code could look:
```python
data = decode_data(s.recv(1024))
game_lock = thread.Lock()

with game_lock:
  if not validate_player_id(player_id):
    message = "ERROR: It is not your turn yet, please wait until it is your turn to make a selection"
    clients[player_id].sendall(message.encode('utf-8'))
    return
  if not validate_empty_space(row, col):
    message = "ERROR: Space is already occupied, please make another selection"
    clients[player_id].sendall(message.encode('utf-8'))
    return
  board[row][col] = player_shape

  if check_winner(board):
    game_state = "CONCLUDED"
    points[player_id] += 1
    return
  if draw():
    game_state = "CONCLUDED"
    return
  if active_player == "player_1":
    active_player = "player_2"
  else:
    active_player = "player_1"
send_update()
```
### **Extra Note:**
- The server gathered the connected players into a dictionary that tracks player IDs and their respective sockets. Restricting access to the server within the shared resource space prevents any other players from manipulating the list, which could cause issues, such as breaking the game, or add in another player that did not connect from the beginning. Similar to how the game board is strictly mutated by the server in the shared resource space, players' points are also kept in the shared resource. By having the players' points in the shared resource, this prevents any sort of cheating or point manipulation by the client and allow the server to accurately track how many points each client has and prohibit any other threads from accidentally touching the points. Similar with clients, points will also be a dictionary. The lock will only be acquired when the server makes changes to the game that will determine the players shape, what spot they chose on the board, the client list, and clients' scores. 
