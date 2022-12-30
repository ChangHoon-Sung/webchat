import logging
import os
import time
import asyncio
from aiohttp import web
import aiohttp
import json
import redis.asyncio

REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
SOCKET_SERVER_PORT = int(os.environ.get('SOCKET_SERVER_PORT', 8080))

DEFAULT_ROOM_ID = 0

mylogger = logging.getLogger('webchat')


def init_mylogger():
    mylogger = logging.getLogger('webchat')

    mylogger.setLevel(logging.DEBUG)
    mylogger.propagate = False

    formatter = logging.Formatter(
        '%(levelname)s:%(name)s: [%(asctime)s] [%(process)d] %(message)s')
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    mylogger.addHandler(console_handler)


def get_milli_time() -> int:
    return round(time.time() * 1000)


async def create_user(data, redis_client: redis.asyncio.Redis) -> int:
    name = data['name']
    room_id = DEFAULT_ROOM_ID   # always join the default room
    user_id = await redis_client.incr('next_user_id')

    await redis_client.set(f'user:{user_id}', name)
    await redis_client.sadd(f'room:{room_id}:users', user_id)
    await redis_client.sadd(f'user:{user_id}:rooms', room_id)

    return user_id


async def broadcast(app: web.Application, pubsub: redis.client.PubSub) -> None:
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True)
            if msg:
                for ws in app['websocket'].copy():
                    if not ws.closed:
                        try:
                            await ws.send_str(msg['data'].decode('utf-8'))
                        except asyncio.CancelledError as e:
                            mylogger.warning(
                                f'broadcast: cancelled')
                            raise
                        except ConnectionResetError as e:
                            # ignore the error when the websocket is closing
                            mylogger.warning(
                                f'broadcast: ignore closing websocket')
                            pass
    except asyncio.CancelledError:
        mylogger.warning(
            f'broadcast: cancelled')
        raise
    except Exception as e:
        mylogger.warning(
            f'%(process)d broadcast: {type(e).__name__}: {e}')


async def init_redis(app: web.Application) -> None:
    try:
        app['redis_client'] = await redis.asyncio.Redis(host=REDIS_HOST, port=REDIS_PORT)
        mylogger.info(
            f'init_redis: redis client connected')

        pubsub = app['redis_client'].pubsub()
        await pubsub.subscribe(f'room:{DEFAULT_ROOM_ID}:messages')
        app['redis_broadcast'] = asyncio.create_task(broadcast(app, pubsub))
    except asyncio.CancelledError:
        mylogger.warning(
            f'init_redis: cancelled')
        raise
    except Exception as e:
        mylogger.error(
            f'redis: {type(e).__name__}: {e}')


async def release_all(app: web.Application) -> None:
    for ws in app['websocket'].copy():
        await ws.close()
        mylogger.info(
            f'release_all: websocket connection closed')
    await app['redis_broadcast']
    await app['redis_client'].close()
    mylogger.info(
        f'release_all: redis client closed')


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    try:
        ws = web.WebSocketResponse(receive_timeout=300)  # 5 minutes
        await ws.prepare(request)
        request.app['websocket'].add(ws)
        mylogger.debug(
            f'websocket_handler: connection established')

        next_user_id = await request.app['redis_client'].get('next_user_id')
        if not next_user_id:
            await request.app['redis_client'].set('next_user_id', 0)
            await request.app['redis_client'].set(f'room:{DEFAULT_ROOM_ID}:name', 'General')
    except asyncio.CancelledError:
        mylogger.warning(
            f'websocket_handler: websocket init cancelled')
        raise
    except Exception as e:
        mylogger.error(
            f'websocket_handler: init {type(e).__name__}: {e}')
        if ws is not None:
            if ws in request.app['websocket']:
                request.app['websocket'].discard(ws)
            await ws.close()
            mylogger.warning(
                f'websocket_handler: abnormal websocket connection closed')
        return

    user_id = None
    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data['type'] == 'init':
                    user_id = await create_user(data, request.app['redis_client'])
                    mylogger.info(f'websocket_handler: user {user_id} joined')
                    await request.app['redis_client'].publish(
                        f'room:{DEFAULT_ROOM_ID}:messages', json.dumps({**data, 'user_id': user_id}))
                elif data['type'] == 'msg':
                    await request.app['redis_client'].publish(
                        f'room:{DEFAULT_ROOM_ID}:messages', msg.data)
                    mylogger.info(
                        f'websocket_handler: user {user_id} send message {msg.data}')
                elif data['type'] == 'quit':
                    break
                else:
                    mylogger.warn(
                        f'unknown message type {data["type"]}')
            elif msg.type == aiohttp.WSMsgType.ERROR:
                mylogger.warning(
                    f'websocket_handler: websocket exception found. {ws.exception()}')
    except asyncio.CancelledError:
        mylogger.warning(
            f'websocket_handler: receive_and_publish cancelled')
        pass    # close the connection
    except asyncio.TimeoutError as e:
        mylogger.warning(
            f'websocket_handler: client timeout')
        pass    # close the connection
    except Exception as e:
        mylogger.error(
            f'websocket_handler: unknown exception {type(e).__name__}: {e}')
        pass    # close the connection
    finally:
        request.app['websocket'].remove(ws)
        await ws.close()
        mylogger.info(f'websocket_handler: user {user_id} left')
        mylogger.debug(
            f'websocket_handler: websocket connection closed')

        name = await request.app['redis_client'].get(f'user:{user_id}')
        if name:
            await request.app['redis_client'].publish(f'room:{DEFAULT_ROOM_ID}:messages', json.dumps(
                {'type': 'quit', 'name': name.decode('utf-8'), 'user_id': user_id, 'timestamp': get_milli_time()}))
            # always leave the default room
            await request.app['redis_client'].srem(f'room:{DEFAULT_ROOM_ID}:users', user_id)
            # always leave the default room
            await request.app['redis_client'].srem(f'user:{user_id}:rooms', DEFAULT_ROOM_ID)
            await request.app['redis_client'].delete(f'user:{user_id}')


async def index(request: web.Request) -> web.Response:
    return web.FileResponse('index.html')

if __name__ == '__main__':
    app = web.Application()
    app.add_routes([
        web.get('/', index),
        web.get('/chat', websocket_handler)
    ])
    app['websocket'] = set()
    app.on_startup.append(init_redis)
    app.on_shutdown.append(release_all)

    init_mylogger()
    logging.basicConfig(level=logging.DEBUG)

    web.run_app(
        app,
        port=SOCKET_SERVER_PORT,
        access_log=logging.getLogger('aiohttp.websocket'),
        access_log_format=f' %t %a webchat %P %r %s %b',
    )
