"""The bench AI service: one asyncio process makes provider calls for every site, so no RQ worker waits on a model.

Run it once per bench under supervisor or systemd, which restart it:
`env/bin/python -m relay_core.ai.remote.daemon --sites sites --callback http://127.0.0.1:8000`
"""
import argparse
import asyncio
import contextlib
import glob
import json
import logging
import os
import signal
import socket
import time
from collections import Counter

import httpx
from redis import asyncio as aioredis
from redis.exceptions import ResponseError

from relay_core.ai.remote import protocol

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
CALLBACK_TIMEOUT = 10
CALLBACK_DELAYS = (0, 1, 5)
RECLAIM_IDLE_MS = 120_000  # Longer than any provider call plus its callbacks.
log = logging.getLogger('relay_ai_service')


class CallbackError(RuntimeError):
    pass


def load_sites(sites_path: str) -> dict[str, str]:
    """{site: secret} of every site that turned the service on in its own site_config.json."""
    sites = {}
    for path in glob.glob(os.path.join(sites_path, '*', 'site_config.json')):
        try:
            with open(path, encoding='utf-8') as file:
                config = json.load(file)
        except (OSError, ValueError):
            continue
        secret = config.get('relay_ai_service_secret') or ''
        site = os.path.basename(os.path.dirname(path))
        if config.get('relay_ai_service') and len(secret) >= protocol.MIN_SECRET and protocol.SITE.fullmatch(site):
            sites[site] = secret
    return sites


class Service:
    def __init__(self, redis, http: httpx.AsyncClient, sites: dict[str, str], callback: str, *,
                 site_limit: int = 20, total_limit: int = 200, consumer: str | None = None):
        self.redis, self.http, self.sites, self.callback_url = redis, http, sites, callback.rstrip('/')
        self.site_limit, self.total_limit, self.total = site_limit, total_limit, asyncio.Semaphore(total_limit)
        self.limits: dict[str, asyncio.Semaphore] = {}
        self.consumer = consumer or f'{socket.gethostname()}:{os.getpid()}'
        self.tasks: set[asyncio.Task] = set()
        self.held: set[tuple[str, str]] = set()  # (site, entry id) of every entry this process works on.
        self.groups: set[str] = set()
        self.counts, self.active, self.taken = Counter(), Counter(), Counter()
        self.stopping = asyncio.Event()

    async def run(self, sites_path: str | None = None) -> None:
        await self.ensure_groups()
        loops = [self.read(), self.reclaim(), self.beat(sites_path)]
        await asyncio.gather(*loops)
        if self.tasks:
            await asyncio.wait(self.tasks, timeout=30)

    async def ensure_groups(self) -> None:
        for site in set(self.sites) - self.groups:
            with contextlib.suppress(ResponseError):  # BUSYGROUP: the group exists.
                await self.redis.xgroup_create(protocol.stream(site), protocol.GROUP, id='0', mkstream=True)
            self.groups.add(site)

    async def read(self) -> None:
        """Read ahead at most `site_limit` entries per site, so one site's backlog cannot hold back another site."""
        while not self.stopping.is_set():
            room = {protocol.stream(site): '>' for site in self.sites
                    if site in self.groups and self.taken[site] < self.site_limit}
            if not room or len(self.tasks) >= self.total_limit + self.site_limit:
                await asyncio.sleep(0.05)
                continue
            batches = await self.redis.xreadgroup(protocol.GROUP, self.consumer, room, count=self.site_limit, block=1000)
            for stream, entries in batches or []:
                site = (stream.decode() if isinstance(stream, bytes) else stream).removeprefix(protocol.STREAM_PREFIX)
                for entry_id, fields in entries:
                    self.spawn(site, entry_id, fields, 1)

    async def reclaim(self) -> None:
        """Take over entries a crashed service read but never acknowledged; skip entries this process still holds."""
        while not self.stopping.is_set():
            for site in list(self.groups):
                start = '0-0'
                while True:
                    start, entries, _ = await self.redis.xautoclaim(protocol.stream(site), protocol.GROUP, self.consumer,
                                                                    RECLAIM_IDLE_MS, start_id=start, count=50)
                    for entry_id, fields in entries:
                        if (site, entry_id) in self.held:
                            continue
                        pending = await self.redis.xpending_range(protocol.stream(site), protocol.GROUP, entry_id,
                                                                  entry_id, 1)
                        self.spawn(site, entry_id, fields,
                                   pending[0]['times_delivered'] if pending else protocol.MAX_DELIVERIES + 1)
                    if start in ('0-0', b'0-0'):
                        break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.stopping.wait(), 30)

    async def beat(self, sites_path: str | None) -> None:
        while not self.stopping.is_set():
            if sites_path:
                self.sites = load_sites(sites_path)
                await self.ensure_groups()
            await self.redis.set(protocol.HEARTBEAT, json.dumps(self.status), ex=protocol.HEARTBEAT_SECONDS)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.stopping.wait(), 5)

    @property
    def status(self) -> dict:
        return {'ts': time.time(), 'consumer': self.consumer, 'in_flight': sum(self.active.values()),
                'queued': len(self.tasks), 'active': dict(self.active), 'counts': dict(self.counts)}

    def spawn(self, stream_site: str, entry_id, fields: dict, deliveries: int) -> None:
        held = (stream_site, entry_id)
        self.held.add(held)
        self.taken[stream_site] += 1
        task = asyncio.create_task(self.handle(stream_site, entry_id, fields, deliveries))
        self.tasks.add(task)

        def done(task):
            self.tasks.discard(task)
            self.held.discard(held)
            self.taken[stream_site] -= 1
        task.add_done_callback(done)

    async def handle(self, stream_site: str, entry_id, fields: dict, deliveries: int) -> None:
        fields = {key.decode() if isinstance(key, bytes) else key: value.decode() if isinstance(value, bytes) else value
                  for key, value in fields.items()}
        try:
            site, identifier = protocol.verify_entry(self.sites, fields)
            if site != stream_site:
                raise protocol.InvalidSignature("Entry is on another site's stream")
        except protocol.InvalidSignature as error:
            log.warning('dropped entry %s: %s', entry_id, error)  # The site's watchdog fails its run.
            self.counts['rejected'] += 1
            await self.redis.xack(protocol.stream(stream_site), protocol.GROUP, entry_id)
            return
        try:
            if deliveries > protocol.MAX_DELIVERIES:
                outcome = {'error': 'lost', 'detail': 'The AI service restarted during this request'}
            else:
                async with self.limit(site), self.total:
                    self.active[site] += 1
                    try:
                        outcome = await self.call(site, identifier)
                    finally:
                        self.active[site] -= 1
            if outcome is not None:
                await self.callback(site, 'result', dict(outcome, id=identifier))
            await self.redis.xack(protocol.stream(site), protocol.GROUP, entry_id)
            self.counts['error' if outcome and outcome.get('error') else 'done'] += 1
        except (CallbackError, httpx.HTTPError) as error:
            log.warning('site %s request %s left for reclaim: %s', site, identifier[:12], error)
            self.counts['unreported'] += 1

    def limit(self, site: str) -> asyncio.Semaphore:
        if site not in self.limits:
            self.limits[site] = asyncio.Semaphore(self.site_limit)
        return self.limits[site]

    async def call(self, site: str, identifier: str) -> dict | None:
        """The provider's raw answer, or the error the site turns into a failed turn. Credentials live only here."""
        spec = await self.callback(site, 'request', {'id': identifier})
        if spec.get('status') != 'ready':
            return None
        timeout = min(float(spec['timeout']), float(spec['deadline']) - time.time())
        if timeout <= 0:
            return {'error': 'timeout', 'detail': 'The request expired in the AI service queue'}
        try:
            async with asyncio.timeout(timeout):
                async with self.http.stream('POST', spec['url'], headers=spec['headers'], json=spec['body']) as answer:
                    body = bytearray()
                    async for chunk in answer.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            return {'error': 'unavailable', 'detail': 'The AI provider answer is too large'}
                    return {'status': answer.status_code, 'body': body.decode('utf-8', 'replace')}
        except TimeoutError:
            return {'error': 'timeout', 'detail': 'The AI provider did not answer in time'}
        except httpx.HTTPError as error:
            return {'error': 'unavailable', 'detail': f'AI provider request failed: {type(error).__name__}'}

    async def callback(self, site: str, method: str, payload: dict) -> dict:
        raw = protocol.canonical(payload)
        url = f'{self.callback_url}/api/method/relay_core.ai.remote.site.{method}'
        error = None
        for delay in CALLBACK_DELAYS:
            await asyncio.sleep(delay)
            timestamp = int(time.time())
            headers = {'Host': site, 'Content-Type': 'application/json', 'X-Relay-AI-Timestamp': str(timestamp),
                       'X-Relay-AI-Signature': protocol.sign(self.sites[site], method, raw, timestamp)}
            try:
                answer = await self.http.post(url, content=raw, headers=headers, timeout=CALLBACK_TIMEOUT)
            except httpx.HTTPError as exc:
                error = exc
                continue
            if answer.status_code == 200:
                return answer.json()['message']
            error = CallbackError(f'{method} answered HTTP {answer.status_code}')
            if answer.status_code < 500:
                break
        raise CallbackError(str(error))


async def serve(arguments) -> None:
    redis = aioredis.from_url(arguments.redis)
    limits = httpx.Limits(max_connections=arguments.total_limit + 50, max_keepalive_connections=100)
    async with httpx.AsyncClient(limits=limits, timeout=None) as http:
        service = Service(redis, http, load_sites(arguments.sites), arguments.callback,
                          site_limit=arguments.site_limit, total_limit=arguments.total_limit)
        loop = asyncio.get_running_loop()
        for name in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(name, service.stopping.set)
        log.info('serving %s', ', '.join(sorted(service.sites)) or 'no sites yet')
        await service.run(arguments.sites)
    await redis.aclose()


def bench_redis(sites_path: str) -> str:
    with open(os.path.join(sites_path, 'common_site_config.json'), encoding='utf-8') as file:
        return json.load(file)['redis_queue']


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--sites', required=True, help='The bench sites folder')
    parser.add_argument('--callback', required=True, help='The bench web server, for example http://127.0.0.1:8000')
    parser.add_argument('--redis', help="Redis URL of the request stream; the bench's redis_queue by default")
    parser.add_argument('--site-limit', type=int, default=20, help='Provider calls in flight per site')
    parser.add_argument('--total-limit', type=int, default=200, help='Provider calls in flight for the bench')
    arguments = parser.parse_args()
    arguments.redis = arguments.redis or bench_redis(arguments.sites)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    asyncio.run(serve(arguments))


if __name__ == '__main__':
    main()
