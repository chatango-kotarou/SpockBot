from spock.mcp.mcpacket import Packet
from spock.net.cflags import cflags

#Will relentlessly try to reconnect to a server
class ReConnectPlugin:
	def __init__(self, client):
		self.client = client
		self.kill = False
		client.register_handler(self.reconnect, 
			cflags['SOCKET_ERR'], cflags['SOCKET_HUP'], cflags['LOGIN_ERR'], cflags['AUTH_ERR'])
		client.register_handler(self.stop, cflags['KILL_EVENT'])
		client.register_dispatch(self.reconnect, 0xFF)
		client.register_dispatch(self.grab_host, 0x02)

	def reconnect(self, *args):
		if not self.kill:
			self.client.login(self.host, self.port)

	#Grabs host and port on handshake
	def grab_host(self, packet):
		self.host = packet.data['host']
		self.port = packet.data['port']

	def stop(self, *agrs):
		self.kill = True
