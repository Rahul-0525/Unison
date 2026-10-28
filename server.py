#!/usr/bin/env python3
import argparse
import asyncio
import io
import json
import logging
import os
import re
import secrets
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from aiohttp import web, WSMsgType, ClientSession, ClientTimeout

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    import qrcode
    import qrcode.image.svg
except ImportError:
    qrcode = None

ROOT = Path(__file__).parent.resolve()
CACHE = ROOT / "cache"
RESOURCES = ROOT / "resources"
LEAD_MS = 1200
MAX_CACHE_FILES = 30
HOST_KEY = os.environ.get("UNISON_HOST_KEY") or secrets.token_urlsafe(8)
OPEN_HOST = os.environ.get("UNISON_OPEN_HOST", "").lower() in ("1", "true", "yes")
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
UPLOAD_EXT = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav", ".webm", ".weba", ".mp4"}

FORMAT = os.environ.get("UNISON_FORMAT", "bestaudio/best")
COOKIES_FROM = os.environ.get("UNISON_COOKIES_FROM")

log = logging.getLogger("unison")


def now_ms() -> float:
    return time.time() * 1000.0


def lan_ips() -> list:
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return [ip for ip in ips if not ip.startswith("127.")]


LAN_IPS = lan_ips()


def is_host(request, key: str = "") -> bool:
    if OPEN_HOST:
        return True
    remote = request.remote or ""
    if remote in LOOPBACK or remote in LAN_IPS:
        return True
    key = key or request.headers.get("X-Host-Key", "") or request.query.get("key", "")
    return bool(key) and secrets.compare_digest(key, HOST_KEY)


@dataclass
class Client:
    id: str
    ws: web.WebSocketResponse
    name: str = "Device"
    host: bool = False
    joined: bool = False
    ready: bool = False
    loading: float = 0.0
    rtt: float = 0.0
    drift: float = 0.0


class Room:
    def __init__(self):
        self.clients = {}
        self.track = None
        self.playing = False
        self.pos = 0.0
        self.at = 0.0
        self.busy = False
        self._end = None

    def position(self) -> float:
        if not self.playing:
            return self.pos
        return self.pos + max(0.0, now_ms() - self.at) / 1000.0

    def state_msg(self) -> dict:
        return {
            "type": "state",
            "playing": self.playing,
            "pos": self.pos,
            "at": self.at,
            "now": now_ms(),
            "trackId": self.track["id"] if self.track else None,
        }

    async def broadcast(self, msg: dict, hosts_only=False, skip=None):
        data = json.dumps(msg)
        targets = [c for c in list(self.clients.values())
                   if c is not skip and c.joined and (c.host or not hosts_only)]
        await asyncio.gather(*(self._send(c, data) for c in targets), return_exceptions=True)

    @staticmethod
    async def _send(c: Client, data: str):
        await c.ws.send_str(data)

    async def push_devices(self):
        devices = [
            {"id": c.id, "name": c.name, "host": c.host, "ready": c.ready,
             "loading": round(c.loading, 2), "rtt": round(c.rtt, 1), "drift": round(c.drift, 1)}
            for c in self.clients.values() if c.joined
        ]
        await self.broadcast({"type": "devices", "devices": devices})

    def arm_end(self):
        if self._end:
            self._end.cancel()
            self._end = None
        if not (self.playing and self.track and self.track.get("duration")):
            return
        remaining = (self.track["duration"] - self.pos) + max(0.0, self.at - now_ms()) / 1000.0 + 0.4
        loop = asyncio.get_running_loop()
        self._end = loop.call_later(max(0.5, remaining), lambda: asyncio.ensure_future(self.finish()))

    async def finish(self):
        if self.playing:
            self.playing, self.pos = False, 0.0
            await self.broadcast(self.state_msg())

    async def play(self, pos=None):
        if not self.track:
            return
        if pos is None:
            pos = self.position()
        dur = self.track.get("duration") or 0
        if dur and pos >= dur - 0.2:
            pos = 0.0
        self.playing, self.pos, self.at = True, float(pos), now_ms() + LEAD_MS
        self.arm_end()
        await self.broadcast(self.state_msg())

    async def pause(self):
        if not self.playing:
            return
        self.pos = self.position()
        self.playing = False
        self.arm_end()
        await self.broadcast(self.state_msg())

    async def seek(self, pos):
        dur = (self.track or {}).get("duration") or 0
        pos = max(0.0, float(pos))
        if dur:
            pos = min(pos, max(0.0, dur - 0.3))
        if self.playing:
            await self.play(pos)
        else:
            self.pos = pos
            await self.broadcast(self.state_msg())

    async def set_track(self, track: dict):
        self.track = track
        self.playing, self.pos, self.at = False, 0.0, 0.0
        self.arm_end()
        for c in self.clients.values():
            c.ready, c.loading = False, 0.0
        await self.broadcast({"type": "track", "track": track})
        await self.broadcast(self.state_msg())
        await self.push_devices()


room = Room()


async def ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=15, max_msg_size=2 ** 20)
    await ws.prepare(request)
    c = Client(id=secrets.token_hex(3), ws=ws)
    room.clients[c.id] = c
    try:
        async for m in ws:
            if m.type != WSMsgType.TEXT:
                continue
            try:
                d = json.loads(m.data)
            except ValueError:
                continue
            await handle(c, d, request)
    finally:
        room.clients.pop(c.id, None)
        await room.push_devices()
    return ws


async def handle(c: Client, d: dict, request):
    t = d.get("type")

    if t == "ping":
        await c.ws.send_str(json.dumps({"type": "pong", "t0": d.get("t0"), "ts": now_ms()}))
        return

    if t == "hello":
        c.name = (str(d.get("name") or "").strip()[:24]) or f"Phone {c.id}"
        has_host = any(other.host for other in room.clients.values() if other.id != c.id)
        c.host = is_host(request, str(d.get("key") or "")) or not has_host
        c.joined = True
        await c.ws.send_str(json.dumps({
            "type": "welcome", "id": c.id, "host": c.host,
            "track": room.track, "state": room.state_msg(),
        }))
        await room.push_devices()
        return

    if not c.joined:
        return

    if t == "ready":
        if room.track and d.get("trackId") == room.track["id"]:
            c.ready, c.loading = True, 1.0
            dur = float(d.get("duration") or 0)
            if dur and not room.track.get("duration"):
                room.track["duration"] = dur
                room.arm_end()
                await room.broadcast({"type": "track", "track": room.track})
            await room.push_devices()
    elif t == "loading":
        if room.track and d.get("trackId") == room.track["id"]:
            c.loading = float(d.get("p") or 0)
            await room.push_devices()
    elif t == "stat":
        c.rtt = float(d.get("rtt") or 0)
        c.drift = float(d.get("drift") or 0)
        await room.push_devices()
    elif t == "rename":
        c.name = (str(d.get("name") or "").strip()[:24]) or c.name
        await room.push_devices()
    elif c.host and t == "play":
        await room.play(d.get("pos"))
    elif c.host and t == "pause":
        await room.pause()
    elif c.host and t == "seek":
        await room.seek(d.get("pos") or 0)
    elif c.host and t == "relay":
        await room.broadcast({"type": "relay", "channel": str(d.get("channel"))[:40],
                              "data": d.get("data")}, skip=c)


def prune_cache(keep: str):
    files = sorted((p for p in CACHE.iterdir() if p.is_file()),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[MAX_CACHE_FILES:]:
        if p.name != keep:
            try:
                p.unlink()
            except OSError:
                pass


def download(url: str, hook):
    opts = {
        "format": FORMAT,
        "outtmpl": str(CACHE / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "progress_hooks": [hook],
    }
    if COOKIES_FROM:
        opts["cookiesfrombrowser"] = (COOKIES_FROM,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info.get("entries"):
            info = info["entries"][0]
        rd = (info.get("requested_downloads") or [{}])[0]
        path = Path(rd.get("filepath") or ydl.prepare_filename(info))
    return info, rd, path


def clean_song_info(raw_title: str, raw_artist: str = "") -> tuple:
    title = (raw_title or "").strip()
    artist = (raw_artist or "").strip()

    artist = re.sub(r"\s*-\s*Topic$", "", artist, flags=re.I)
    artist = re.sub(r"VEVO$", "", artist, flags=re.I)

    m = re.match(r"^([^–\-:|]+?)\s*[–\-:|]\s*(.+)$", title)
    if m:
        p1, p2 = m.group(1).strip(), m.group(2).strip()
        if not artist or artist.lower() in p1.lower() or p1.lower() in artist.lower():
            artist = p1
            title = p2

    noise_patterns = [
        r"\s*[\(\[]\s*(official\s*(music\s*)?video|official\s*audio|lyrics?\s*video|visualizer|audio|hd|4k|remaster(ed)?|live(\s*at.*)?|clip\s*officiel|video\s*clip|explicit)\s*[\)\]]",
        r"\s*[\(\[]\s*lyrics?\s*[\)\]]",
        r"\s*[\(\[]\s*(prod\.?|produced\s*by)\s+[^)\]]+[\)\]]",
        r"\s*[\(\[]\s*(ft\.?|feat\.?|featuring)\s+[^)\]]+[\)\]]",
        r"\s*(ft\.?|feat\.?|featuring)\s+[\w\s&]+(?=[\(\[]|$)",
    ]
    for p in noise_patterns:
        title = re.sub(p, "", title, flags=re.I)

    title = re.sub(r"\s{2,}", " ", title).strip()
    return title, artist


def search_yt(query: str, max_results: int = 15):
    opts = {
        "format": FORMAT,
        "quiet": True,
        "extract_flat": True,
        "noplaylist": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        res = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
        entries = res.get("entries") or []
        items = []
        for e in entries:
            if not e:
                continue
            vid = e.get("id") or ""
            raw_title = e.get("title") or ""
            raw_artist = e.get("uploader") or e.get("channel") or ""
            cleaned_title, cleaned_artist = clean_song_info(raw_title, raw_artist)

            thumbs = e.get("thumbnails") or []
            thumb = e.get("thumbnail") or (thumbs[-1].get("url") if thumbs else "")
            if not thumb and vid:
                thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

            items.append({
                "id": vid,
                "title": cleaned_title or raw_title,
                "artist": cleaned_artist or raw_artist,
                "duration": float(e.get("duration") or 0),
                "thumbnail": thumb,
                "url": f"https://www.youtube.com/watch?v={vid}",
            })
        return items


async def api_search(request):
    q = request.query.get("q", "").strip()
    if not q:
        return web.json_response([], headers={"Access-Control-Allow-Origin": "*"})
    if yt_dlp is None:
        return web.json_response({"error": "yt-dlp is not installed"}, status=500)
    loop = asyncio.get_running_loop()
    try:
        results = await loop.run_in_executor(None, search_yt, q)
        return web.json_response(results, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as e:
        log.warning("search failed for %s: %s", q, e)
        return web.json_response([], headers={"Access-Control-Allow-Origin": "*"})


async def api_load(request):
    if not is_host(request):
        raise web.HTTPForbidden(text="Only the host can load songs.")
    if yt_dlp is None:
        return web.json_response({"error": "yt-dlp is not installed. Run: pip install -U yt-dlp"}, status=500)
    try:
        url = str((await request.json()).get("url") or "").strip()
    except ValueError:
        url = ""
    if not url.startswith(("http://", "https://")):
        return web.json_response({"error": "That doesn't look like a link."}, status=400)
    if room.busy:
        return web.json_response({"error": "Another song is still loading."}, status=409)

    room.busy = True
    loop = asyncio.get_running_loop()
    last = [0.0]

    def hook(d):
        if d.get("status") != "downloading" or time.time() - last[0] < 0.2:
            return
        last[0] = time.time()
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        pct = (d.get("downloaded_bytes") or 0) / total if total else 0
        asyncio.run_coroutine_threadsafe(room.broadcast({"type": "dl", "pct": pct}, hosts_only=True), loop)

    try:
        await room.broadcast({"type": "dl", "pct": 0.01}, hosts_only=True)
        info, rd, path = await loop.run_in_executor(None, download, url, hook)
    except Exception as e:
        msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "")
        log.warning("download failed: %s", msg)
        return web.json_response({"error": msg[:300]}, status=502)
    finally:
        room.busy = False

    raw_title = info.get("track") or info.get("title") or path.stem
    raw_artist = info.get("artist") or info.get("uploader") or ""
    clean_t, clean_a = clean_song_info(raw_title, raw_artist)

    track = {
        "id": secrets.token_hex(4),
        "title": clean_t or raw_title,
        "artist": clean_a or raw_artist,
        "duration": float(info.get("duration") or 0),
        "thumbnail": info.get("thumbnail") or "",
        "url": "/media/" + quote(path.name),
        "bytes": path.stat().st_size,
        "codec": (rd.get("acodec") or info.get("acodec") or "").split(".")[0],
        "abr": rd.get("abr") or info.get("abr") or 0,
        "source": "youtube",
    }
    prune_cache(path.name)
    await room.set_track(track)
    return web.json_response({"ok": True, "track": track})


async def api_upload(request):
    if not is_host(request):
        raise web.HTTPForbidden(text="Only the host can upload songs.")
    reader = await request.multipart()
    part = await reader.next()
    if part is None or not part.filename:
        return web.json_response({"error": "No file received."}, status=400)
    orig = Path(part.filename).name
    ext = Path(orig).suffix.lower()
    if ext not in UPLOAD_EXT:
        return web.json_response({"error": f"{ext or 'That'} files aren't supported."}, status=400)
    fname = f"up_{secrets.token_hex(4)}{ext}"
    size = 0
    with open(CACHE / fname, "wb") as f:
        while True:
            chunk = await part.read_chunk(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            f.write(chunk)
    track = {
        "id": secrets.token_hex(4), "title": Path(orig).stem, "artist": "", "duration": 0.0,
        "thumbnail": "", "url": "/media/" + quote(fname), "bytes": size,
        "codec": ext.lstrip("."), "abr": 0, "source": "upload",
    }
    prune_cache(fname)
    await room.set_track(track)
    return web.json_response({"ok": True, "track": track})


async def api_whoami(request):
    port = request.app["port"]
    key = request.query.get("key", "")
    has_host = any(c.host for c in room.clients.values())
    host_status = is_host(request, key) or not has_host
    return web.json_response({
        "host": host_status,
        "urls": [f"http://{ip}:{port}/" for ip in LAN_IPS],
        "ytdlp": yt_dlp is not None,
    })


async def api_proxy_image(request):
    url = request.query.get("url", "").strip()
    if not url.startswith(("http://", "https://")) or len(url) > 1024:
        raise web.HTTPBadRequest()
    try:
        timeout = ClientTimeout(total=8)
        async with ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
                if resp.status != 200:
                    raise web.HTTPBadGateway()
                ct = resp.headers.get("Content-Type", "image/jpeg")
                data = await resp.read()
                return web.Response(
                    body=data,
                    content_type=ct,
                    headers={
                        "Cache-Control": "public, max-age=86400",
                        "Access-Control-Allow-Origin": "*",
                    },
                )
    except Exception as e:
        log.warning("proxy_image failed for %s: %s", url, e)
        raise web.HTTPBadGateway()


async def api_lyrics(request):
    q = request.query.get("q", "").strip()
    title = request.query.get("title", "").strip()
    artist = request.query.get("artist", "").strip()
    dur = float(request.query.get("duration", 0) or 0)

    clean_t, clean_a = clean_song_info(title, artist)
    queries = []

    if clean_a and clean_t:
        queries.append(f"{clean_a} {clean_t}".strip())
    if q and q not in queries:
        queries.append(q)
    if clean_t and clean_t not in queries:
        queries.append(clean_t)

    timeout = ClientTimeout(total=7)
    headers = {"User-Agent": "Unison-Music/2.0 (https://github.com)"}

    try:
        async with ClientSession(timeout=timeout) as session:
            # 1. Exact /api/get if clean artist and title exist
            if clean_a and clean_t:
                get_url = f"https://lrclib.net/api/get?artist_name={quote(clean_a)}&track_name={quote(clean_t)}"
                if dur > 0:
                    get_url += f"&duration={round(dur)}"
                try:
                    async with session.get(get_url, headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("syncedLyrics") or data.get("plainLyrics"):
                                return web.json_response([data], headers={"Access-Control-Allow-Origin": "*"})
                except Exception:
                    pass

            # 2. Search queries in order of specificity
            for q_str in queries:
                search_url = f"https://lrclib.net/api/search?q={quote(q_str)}"
                try:
                    async with session.get(search_url, headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if isinstance(data, list) and len(data) > 0:
                                return web.json_response(data, headers={"Access-Control-Allow-Origin": "*"})
                except Exception:
                    pass
    except Exception as e:
        log.warning("lyrics fetch failed: %s", e)

    return web.json_response([], headers={"Access-Control-Allow-Origin": "*"})


async def api_qr(request):
    u = request.query.get("u", "")
    if qrcode is None or not u.startswith("http") or len(u) > 300:
        raise web.HTTPNotFound()
    img = qrcode.make(u, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
    buf = io.BytesIO()
    img.save(buf)
    return web.Response(body=buf.getvalue(), content_type="image/svg+xml",
                        headers={"Cache-Control": "max-age=3600"})


async def index(request):
    return web.FileResponse(ROOT / "index.html", headers={"Cache-Control": "no-store"})


def make_app(port: int) -> web.Application:
    CACHE.mkdir(exist_ok=True)
    RESOURCES.mkdir(exist_ok=True)
    app = web.Application(client_max_size=100 * 2 ** 20)
    app["port"] = port
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/api/whoami", api_whoami)
    app.router.add_post("/api/load", api_load)
    app.router.add_post("/api/upload", api_upload)
    app.router.add_get("/api/search", api_search)
    app.router.add_get("/api/proxy_image", api_proxy_image)
    app.router.add_get("/api/lyrics", api_lyrics)
    app.router.add_get("/qr.svg", api_qr)
    app.router.add_static("/media", CACHE, follow_symlinks=False)
    app.router.add_static("/resources", RESOURCES, follow_symlinks=False)
    return app


def banner(port: int):
    line = "-" * 62
    print(f"\n{line}\n  Unison is running\n{line}")
    print(f"  Host (this computer):   http://localhost:{port}/")
    for ip in LAN_IPS:
        print(f"  Devices can join at:    http://{ip}:{port}/")
    if LAN_IPS:
        print(f"  Host from a phone:      http://{LAN_IPS[0]}:{port}/?key={HOST_KEY}")
    print(f"{line}\n")


def main():
    ap = argparse.ArgumentParser(description="Unison - synced multi-device playback")
    ap.add_argument("--host", default="0.0.0.0")
    default_port = int(os.environ.get("PORT", "8765"))
    ap.add_argument("--port", type=int, default=default_port)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    banner(args.port)
    web.run_app(make_app(args.port), host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()