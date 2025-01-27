import asyncio
import logging
import logging.config
from connection import Connection
import ircb.stores
from ircb.models import get_session, Network as NetworkModel, User
from ircb.config import settings
from ircb.storeclient import NetworkStore, ClientStore, ChannelStore
from ircb.irc import IrcbBot


logger = logging.getLogger('bouncer')


class BouncerServerClientProtocol(Connection):

    def __init__(self, get_bot_handle, unregister_client):
        self.network = None
        self.forward = None
        self.get_bot_handle = get_bot_handle
        self.unregister_client = unregister_client
        self.host, self.port = None, None
        self.client_id = None

    def connection_made(self, transport):
        logger.debug('New client connection received')
        self.transport = transport
        self.host, self.port = self.transport.get_extra_info(
            'socket').getpeername()

    def data_received(self, data):
        asyncio.Task(self.handle_data_received(data))

    @asyncio.coroutine
    def handle_data_received(self, data):
        data = self.decode(data)
        logger.debug('Received client data: %s', data)
        for line in data.rstrip().splitlines():
            verb, message = line.split(" ", 1)
            if verb == "QUIT":
                pass
            elif verb == "PASS":
                access_token = message.split(" ")[0]
                self.network = self.get_network(access_token)
                if self.network is None:
                    logger.debug(
                        'Client authentiacation failed for token: {}'.format(
                            access_token))
                    self.unregister_client(self.network.id, self)
                    self.transport.write('Authentication failed')
                    self.transport.close()
                else:
                    client = yield from ClientStore.create({
                        'socket': '{}:{}'.format(self.host, self.port),
                        'network_id': self.network.id,
                        'user_id': self.network.user_id
                    })
                    self.client_id = client.id
            elif self.forward:
                self.forward(line)

            if self.forward is None:
                self.forward = yield from self.get_bot_handle(
                    self.network, self)

    def connection_lost(self, exc):
        self.unregister_client(self.network.id, self)
        logger.debug('Client connection lost: {}'.format(self.network))
        if self.client_id:
            asyncio.Task(ClientStore.delete({'id': self.client_id}))

    def get_network(self, access_token):
        return session.query(NetworkModel).filter(
            NetworkModel.access_token == access_token).first()

    def __str__(self):
        return '<BouncerClientConnection {}:{}>'.format(
            self.host, self.port)

    def __repr__(self):
        return self.__str__()


class Bouncer(object):

    def __init__(self, session):
        self.bots = {}
        self.clients = {}
        self.session = session

    def start(self, host='127.0.0.1', port=9000):
        loop = asyncio.get_event_loop()
        coro = loop.create_server(
            lambda: BouncerServerClientProtocol(self.get_bot_handle,
                                                self.unregister_client),
            host, port)
        logger.info('Listening on {}:{}'.format(host, port))
        bouncer_server = loop.run_until_complete(coro)
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass
        bouncer_server.close()
        loop.run_until_complete(bouncer_server.wait_closed())

    def get_bot_handle(self, network, client):
        try:
            key = network.id
            bot = self.bots.get(key)
            self.register_client(key, client)
            if bot is None:
                user = session.query(User).get(network.user_id)
                logger.debug(
                    'Creating new bot: {}-{}'.format(
                        user.username, network.name)
                )
                yield from NetworkStore.update(
                    dict(
                        filter=('id', network.id),
                        update={
                            'status': '0'
                        })
                )
                config = dict(
                    id=network.id,
                    name=network.name,
                    userinfo=network.username,
                    password=network.password,
                    nick='rtnpro_',
                    realname=network.realname,
                    host=network.hostname,
                    port=network.port
                )
                bot = IrcbBot(**config)
                bot.run_in_loop()
                self.register_bot(key, bot)
            else:
                # FIXME: Discard get_joining_messages() and generate joining
                #        messages dynamically, including channel join messages
                #        so that IRC clients can load the channels.
                logger.debug('Reusing existing bot: {}'.format(bot))
                joining_messages = bot.get_joining_messages()
                client.send(*[joining_messages])
                joining_messages_list = [
                    ':* 001 {nick} :You are now connected to {network}'.format(
                        nick='rtnpro_', network=network.name),
                    ':* 251 {nick} : '.format(nick='rtnpro_')
                ]
                connected_channels = yield from ChannelStore.get({
                    'query': dict(
                        network_id=key,
                        status='1'
                    )
                })
                for channel in connected_channels:
                    # joining_messages_list.append(
                    #    ':{nick}_!* JOIN {channel}'.format(
                    #        nick=network.nickanme,
                    #        channel=channel.name))
                    bot.raw('NAMES', channel.name)

                # client.send(*['\r\n'.join(joining_messages_list)])

            def forward(line):
                bot = self.bots.get(key)
                if bot:
                    logger.debug(
                        'Forwarding {}\t {}'.format(bot, line))
                    bot.raw(line)

            return forward
        except Exception as e:
            logger.error('get_bot_handle error: {}'.format(e),
                         exc_info=True)

    def register_bot(self, network_id, bot):
        logger.debug('Registering new bot: {}'.format(network_id))
        key = network_id
        existing_bot = self.bots.get(key)
        if existing_bot:
            existing_bot.protocol.transport.close()
            del self.bots[key]
        bot.clients = self.clients.get(key, set())
        self.bots[key] = bot
        logger.debug('Bots: %s', self.bots)

    def register_client(self, network_id, client):
        key = network_id
        clients = self.clients.get(key)
        if clients is None:
            clients = set()
            self.clients[key] = clients
        clients.add(client)
        logger.debug('Registered new client: %s, %s', key, clients)

    def unregister_client(self, network_id, client):
        key = network_id
        clients = self.clients.get(key)
        logger.debug('Unregistering client: {}'.format(client))
        try:
            clients.remove(client)
        except KeyError:
            pass

if __name__ == '__main__':
    logging.config.dictConfig(settings.LOGGING_CONF)
    session = get_session()
    ircb.stores.initialize()
    bouncer = Bouncer(session)
    bouncer.start()
