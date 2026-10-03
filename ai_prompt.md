#AI Prompt:
- Currently this is how I've gotten my AI to behave accordingly to my strict guidelines for this project. The prompt could change depending on if the AI starts going off track.
   
-You will adhere to the rules I will show you that will help me along the way with developing my custom application layer protocol and tic tac toe game.
1. You will utilize the newline delimiter JSON framing structure and how the messages are sent to the server will be in JSON only. All JSON messages must terminate in a newline (\n)
2. You will follow along the diagram of my network structure in this image: (image file). For example, there will be two clients, each connected to different sides of the cisco router, and the cisco router is connected to the second cisco router, and the second cisco router will be connected to the server. Do not do anything that will not follow this exact structure.
3. You will follow along what the diagram shows for my custom app layer protocol: (image file). Do not write any generic socket code or any other external code that will stray away from my diagram.
4. You will only use Python as I will be using Python only for this project. Do not use any other languages.
5. In any point where a client could disconnect from the server when both players are connected, make sure that the code is checking to see if a player suddenly disconnects from any error such as ConnectionResetError, BrokenPipeError, or TimeoutError. The only place where an opponent can gracefully disconnect is during gameplay.
6. Do not try adding any IP address or change what I have currently set out, from the network structure example, the IP address will match exactly or almost similar to it.
