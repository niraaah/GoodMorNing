"""CONNECT-only egress gateway. No TLS interception, credentials or host mounts."""
import asyncio
import ipaddress
import socket

EXACT = {'api-gateway.coupang.com','fonts.googleapis.com','fonts.gstatic.com'}
SUFFIXES = ('coupangcdn.com','pstatic.net','pokemonstore.co.kr','daewonshop.com',
    'cdn-nhncommerce.com','nhncommerce.com','shopby.co.kr','shopby-api.com','naver.net','jsdelivr.net')
MAX_BYTES = 32 * 1024 * 1024


def authority(value):
    host, separator, port = value.rpartition(':')
    host = host.lower()
    if not separator or port != '443' or not host or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789.-' for c in host):
        raise ValueError('Denied authority')
    if host not in EXACT and not any(host == domain or host.endswith('.'+domain) for domain in SUFFIXES):
        raise ValueError('Denied destination')
    return host


def public_addresses(records):
    addresses = list(dict.fromkeys(record[4][0] for record in records))
    if not addresses or any(not ipaddress.ip_address(address).is_global or ipaddress.ip_address(address).version != 4 for address in addresses):
        raise ValueError('Non-public DNS response')
    return addresses


async def upstream(host):
    loop = asyncio.get_running_loop()
    records = await asyncio.wait_for(loop.getaddrinfo(host,443,family=socket.AF_INET,type=socket.SOCK_STREAM),5)
    addresses = public_addresses(records)
    for address in addresses[:4]:
        sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        sock.setblocking(False)
        try:
            # Connect to the validated numeric address, never resolve the name a second time.
            await asyncio.wait_for(loop.sock_connect(sock,(address,443)),8)
            return await asyncio.open_connection(sock=sock)
        except (OSError, TimeoutError):
            sock.close()
    raise OSError('Upstream unavailable')


async def handle(reader, writer):
    remote_writer = None
    connected = False
    try:
        peer = writer.get_extra_info('peername')[0]
        if peer not in ('172.30.74.3','172.30.74.4'):
            raise ValueError('Denied caller')
        raw = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),5)
        if len(raw)>8192:
            raise ValueError('Oversized request')
        method, target, version = raw.split(b'\r\n',1)[0].decode('ascii').split(' ')
        if method!='CONNECT' or version not in ('HTTP/1.1','HTTP/1.0'):
            raise ValueError('CONNECT required')
        remote_reader, remote_writer = await upstream(authority(target))
        writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
        await writer.drain()
        connected = True
        budget = [MAX_BYTES]
        async def relay(source, destination):
            while True:
                chunk = await asyncio.wait_for(source.read(65536),25)
                if not chunk:
                    return
                budget[0] -= len(chunk)
                if budget[0]<0:
                    raise ValueError('Transfer limit')
                destination.write(chunk)
                await destination.drain()
        tasks = [asyncio.create_task(relay(reader,remote_writer)),asyncio.create_task(relay(remote_reader,writer))]
        try:
            done, _ = await asyncio.wait(tasks,timeout=120,return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    except (ValueError,OSError,TimeoutError,UnicodeError,asyncio.IncompleteReadError,asyncio.LimitOverrunError):
        if not connected:
            writer.write(b'HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n')
    finally:
        if remote_writer:
            remote_writer.close()
        writer.close()


async def main():
    gate = asyncio.Semaphore(64)
    async def limited(reader,writer):
        if gate.locked():
            writer.close()
            return
        async with gate:
            await handle(reader,writer)
    server = await asyncio.start_server(limited,'0.0.0.0',8080,limit=8192)
    async with server:
        await server.serve_forever()


if __name__=='__main__':
    asyncio.run(main())
