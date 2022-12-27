import asyncio
from aiohttp import web
import aiohttp
import json
import redis
import redis.asyncio
import os

REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))

DEFAULT_ROOM_ID = 0


async def create_user(data, redis_client: redis.asyncio.Redis):
    name = data['name']
    room_id = DEFAULT_ROOM_ID   # always join the default room
    user_id = await redis_client.incr('next_user_id')

    await redis_client.set(f'user:{user_id}', name)
    await redis_client.sadd(f'room:{room_id}:users', user_id)
    await redis_client.sadd(f'user:{user_id}:rooms', room_id)

    return user_id


async def init_redis(redis_client: redis.asyncio.Redis):
    # try:
    #     await redis_client.ping()
    # except redis.exceptions.ConnectionError:
    #     raise

    next_user_id = await redis_client.get('next_user_id')
    if not next_user_id:
        await redis_client.set('next_user_id', 0)
        await redis_client.set(f'room:{DEFAULT_ROOM_ID}:name', 'general')
    

async def websocket_handler(data):
    try:
        ws = web.WebSocketResponse(receive_timeout=10)  # 10 seconds
        await ws.prepare(data)
    except Exception as e:
        print(f'websocket: {e}')
        return

    try:
        redis_client = await redis.asyncio.Redis(host=REDIS_HOST, port=REDIS_PORT)
        await init_redis(redis_client)
        # TODO: redis로 pubsub 구현
        # pubsub = redis_client.pubsub()
        # pubsub.subscribe(f'room:{DEFAULT_ROOM_ID}:messages')
    except redis.exceptions.ConnectionError:
        print('redis connect: Redis is not available')
        return
    except Exception as e:
        print(f'redis init: {e}')
        return

    user_id = None
    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data['type'] == 'init':
                    user_id = await create_user(data, redis_client)
                    await ws.send_str(json.dumps({'type': 'init', 'user_id': user_id, 'room_id': DEFAULT_ROOM_ID}))
                elif data['type'] == 'msg':
                    await ws.send_str(json.dumps({'type': 'msg', 'user_id': user_id, 'content': data['content']}))
                else:
                    print(f'unknown message type {data["type"]}')
            elif msg.type == aiohttp.WSMsgType.ERROR:
                print(f"ws closed with exception {ws.exception()}")
                break
    except asyncio.TimeoutError as e:
        print(f'websocket timeout: user_id {user_id}')
        pass
    except Exception as e:
        print(f'unknown exception {e}')
    finally:
        # always leave the default room
        await redis_client.srem(f'room:{DEFAULT_ROOM_ID}:users', user_id)
        await redis_client.srem(f'user:{user_id}:rooms', DEFAULT_ROOM_ID)
        await redis_client.delete(f'user:{user_id}')
        await redis_client.close()
        await ws.close()
        print(f'websocket connection closed: user_id {user_id}')

if __name__ == '__main__':
    app = web.Application()
    app.add_routes([
        web.get('/chat', websocket_handler)
    ])
    web.run_app(app, port=5500)
