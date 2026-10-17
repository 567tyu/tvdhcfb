from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncio
import aiohttp
import re
from typing import List, Optional
import time

app = FastAPI(title="DirSweeper - Directory Scanner")

COMMON_PATHS = [
    "", "/", "/index.html", "/index.htm", "/home",
    "/about", "/contact", "/contact-us", "/about-us",
    "/blog", "/news", "/articles",
    "/admin", "/administrator", "/admin panel", "/wp-admin",
    "/login", "/logout", "/signup", "/register", "/auth",
    "/api", "/api/v1", "/api/v2", "/graphql", "/graphiql",
    "/dashboard", "/panel", "/control", "/cpanel",
    "/config", "/configuration", "/settings",
    "/static", "/assets", "/media", "/images", "/css", "/js",
    "/docs", "/documentation", "/help", "/support",
    "/favicon.ico", "/robots.txt", "/sitemap.xml", "/.env",
    "/.git", "/.gitignore", "/.svn", "/.htaccess",
    "/wp-login.php", "/wp-content", "/wp-includes",
    "/xmlrpc.php", "/wp-config.php",
    "/phpmyadmin", "/mysql", "/db", "/database",
    "/server-status", "/server-info", "/info", "/phpinfo",
    "/test", "/testing", "/staging", "/dev",
    "/backup", "/backups", "/dump", "/sql",
    "/upload", "/uploads", "/files", "/file",
    "/search", "/logout", "/profile", "/user", "/users",
    "/product", "/products", "/shop", "/store", "/cart",
    "/order", "/orders", "/checkout",
    "/tag", "/tags", "/category", "/categories",
    "/feed", "/rss", "/atom",
    "/health", "/healthz", "/status", "/ping",
    "/metrics", "/prometheus",
    "/ swagger-ui ", "/swagger", "/openapi",
    "/actuator", "/actuator/health",
    "/debug", "/trace",
]

class ScanRequest(BaseModel):
    url: str
    thread_count: int = 50
    timeout: float = 3.0
    follow_redirects: bool = False

class ScanResult(BaseModel):
    path: str
    status: int
    words: int
    title: Optional[str] = None
    scan_id: str

class ScanStatus(BaseModel):
    scan_id: str
    status: str
    progress: int
    total: int
    results: List[dict]

scans = {}
scan_counter = 0

def generate_scan_id():
    global scan_counter
    scan_counter += 1
    return f"scan_{int(time.time())}_{scan_counter}"

async def scan_directory(session: aiohttp.ClientSession, base_url: str, path: str, timeout: float) -> Optional[dict]:
    try:
        if not path:
            full_url = base_url
        else:
            base = base_url.rstrip('/')
            full_url = f"{base}/{path.lstrip('/')}"

        async with session.get(
            full_url,
            timeout=aiohttp.ClientTimeout(total=timeout),
            allow_redirects=False,
            headers={
                "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/111.0.0.0 Mobile Safari/537.36"
            }
        ) as resp:
            body = await resp.text()
            words = len(body.split())
            title_match = re.search(r'<title[^>]*>([^<]+)</title>', body, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else None
            return {
                "path": path if path else "/",
                "status": resp.status,
                "words": words,
                "title": title,
                "url": full_url
            }
    except Exception:
        return None

@app.post("/api/scan/start")
async def start_scan(req: ScanRequest):
    scan_id = generate_scan_id()
    base_url = req.url.strip()
    if not base_url.startswith(('http://', 'https://')):
        base_url = 'https://' + base_url
    if not base_url.endswith('/'):
        base_url += '/'

    scans[scan_id] = {
        "status": "running",
        "base_url": base_url,
        "thread_count": req.thread_count,
        "timeout": req.timeout,
        "results": [],
        "progress": 0,
        "total": len(COMMON_PATHS),
        "start_time": time.time()
    }

    loop = asyncio.get_event_loop()

    async def run_scan():
        connector = aiohttp.TCPConnector(limit=req.thread_count, limit_per_host=req.thread_count)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [scan_directory(session, base_url, path, req.timeout) for path in COMMON_PATHS]
            completed = 0
            for coro in asyncio.as_completed(tasks):
                result = await coro
                if result:
                    scans[scan_id]["results"].append(result)
                completed += 1
                scans[scan_id]["progress"] = completed
            scans[scan_id]["status"] = "completed"
            scans[scan_id]["end_time"] = time.time()
            scans[scan_id]["duration"] = scans[scan_id]["end_time"] - scans[scan_id]["start_time"]

    asyncio.ensure_future(run_scan())
    return {"scan_id": scan_id, "total_paths": len(COMMON_PATHS)}

@app.get("/api/scan/{scan_id}")
async def get_scan_status(scan_id: str):
    if scan_id not in scans:
        raise HTTPException(status_code=404, detail="Scan not found")
    scan = scans[scan_id]
    results_sorted = sorted(scan["results"], key=lambda x: (-x["status"] >= 200, x["status"]))
    return {
        "scan_id": scan_id,
        "status": scan["status"],
        "progress": scan["progress"],
        "total": scan["total"],
        "results": results_sorted
    }

@app.get("/api/health")
async def health():
    return {"status": "ok"}
