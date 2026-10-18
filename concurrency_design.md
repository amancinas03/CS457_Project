## Server Concurrency Strategy
- ### **Architecture Choice:** Multi-Threading (`threading.Thread`)
- The server will utilize a multi-threaded threading.Thread to ensure that each client that connected would automatically be binded to a thread from the server. For example, the server will still use bind() to bind the IP address and port number and listen() to let the players connect.
- Once each connected the server will use the threading.Thread(target=handle_client, args=(client_socket, client_address, player_id)) after client_socket, client_address = socket.accept() and server assigning the unique player id. The server will then start that thread for each player connected.
- ### **Synchronization Logic:** 
- After binding the connections of both players, threading.Lock from here on out will be utilized to ensure mutex exclusion. When a player who goes first chooses their shape, the server will first verify the validity of the shape, then acquire the lock, such as lock.acquire().
- The server will be updating variables in the shared space of the shape each player will now have, releases that lock, such as lock.release(), and then send a state update.
  However, if a player abruptly disconnects, the server will catch that, acquires the lock, clean up the game fast, release the lock, and return the remaining player back to the lobby.
  After the assigning process has been complete the game will begin:
1. The first player will have their turn = True, indicating that they're an active player. The inactive opponent will have their turn = False. The inactive play will in `if not turn: socket.recv(1024)` section, until the server sends the update.
2.  The active player will make their choice in the board, such as row = 0, col = 2. The server will know the shape of each player. The active player will then convert their data into a JSON payload/message with json.dumps(data).encode("utf-8"), with data containing: *data = {}, data["player_id"] = id, data["row"] = 0, and data["col"] = 2*.
3. The player will send it into the socket created to the server, such as `socket.sendall(data).
4. The server will then do lock.acquire() to ensure no one enters the shared resource
5. The server will validate the ID with the current player ID it is looking for, then check if their choice is within the board and not on an already chosen spot. 
6. If they're both valid, the server will then swap the turns for the players, update the board, releases the locks, and then send an update to both player.
7. These actions will repeat until the server finds a winning 3 in a row or draw.
- When the game concludes by winning or draw, the server will acquire a lock and determine if any player will earn a score or not depending on the winning condition. It will release the lock and asks if the players would want a rematch.
  If so, the server will acquire the lock one more time, clean up the board, set the player who didn't go first last game to be the one to go first, and start all the way back to the beginning.
  If a player disconnects in the middle of the game, the server will also catch that instance, acquires the lock, clean up the game, make the remaining player the winner, close the socket, and allow the player to go back to the lobby.
  If the players decides not to do a rematch, the server will acquire the lock one more time, clean everything up, close the sockets, and release the lock to allow the player to go back to the lobby.
