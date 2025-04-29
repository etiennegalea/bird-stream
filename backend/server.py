import socket
from uvicorn import Config, Server

# Create an IPv6 socket and allow dual-stack (IPv4 & IPv6)
sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, False)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
sock.bind(("::", 8051))
sock.listen(100)

# Configure and run Uvicorn using the existing ASGI app
config = Config("src.app:app", log_level="info", workers=1)
server = Server(config)

if __name__ == "__main__":
    server.run(sockets=[sock]) 