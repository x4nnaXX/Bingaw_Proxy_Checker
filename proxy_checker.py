import os
import sys
import time
import csv
import aiohttp
import asyncio
import argparse
import ipaddress
from colorama import Fore, Style, init
from tqdm import tqdm
import warnings
import logging

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)
init(autoreset=True)
working_count = 0
output_lock = asyncio.Lock()

BANNER = r"""
 ██████╗ ██╗  ██╗██████╗ ██╗███╗   ██╗ ██████╗  █████╗ ██╗    ██╗
██╔═████╗╚██╗██╔╝██╔══██╗██║████╗  ██║██╔════╝ ██╔══██╗██║    ██║
██║██╔██║ ╚███╔╝ ██████╔╝██║██╔██╗ ██║██║  ███╗███████║██║ █╗ ██║
████╔╝██║ ██╔██╗ ██╔══██╗██║██║╚██╗██║██║   ██║██╔══██║██║███╗██║
╚██████╔╝██╔╝ ██╗██████╔╝██║██║ ╚████║╚██████╔╝██║  ██║╚███╔███╔╝
 ╚═════╝ ╚═╝  ╚═╝╚═════╝ ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝ ╚══╝╚══╝
"""

def clear_terminal():
    # Clear terminal, ignore any error
    try:
        os.system('cls' if os.name == 'nt' else 'clear')
    except Exception:
        pass

def get_term_width():
    try:
        return os.get_terminal_size().columns
    except Exception:
        return 80

def banner_slideshow(banner, slide_speed=0.05, hold_seconds=4, pause_seconds=2):
    # Slower animation, robust terminal width
    lines = banner.strip('\n').split('\n')
    term_width = get_term_width()
    banner_width = max(len(line) for line in lines)
    space = max(0, term_width - banner_width)
    # Slide from left to center
    for pad in range(0, space + 1, 2):
        clear_terminal()
        for line in lines:
            print(' ' * pad + line)
        time.sleep(slide_speed)
    # Hold centered
    clear_terminal()
    for line in lines:
        print(' ' * (space // 2) + line)
    time.sleep(hold_seconds)
    clear_terminal()
    time.sleep(pause_seconds)

def supports_emoji():
    return sys.platform != "win32" or "WT_SESSION" in os.environ

EMOJI_OK = Fore.YELLOW + "✔" + Style.RESET_ALL if supports_emoji() else Fore.YELLOW + "[OK]" + Style.RESET_ALL

def parse_proxy_line(line):
    line = line.strip()
    if not line: return None
    # IPv6: [2001:db8::1]:3128 or [2001:db8::1]:3128:user:pass
    if line.startswith('['):
        l = line.split(']')
        ip = l[0][1:]
        rest = l[1][1:].split(':')
        if len(rest) == 1 or len(rest) == 3:
            port = rest[0]
            if port.isdigit() and 1 <= int(port) <= 65535:
                if len(rest) == 3:
                    user, pwd = rest[1], rest[2]
                else:
                    user, pwd = None, None
                return f"[{ip}]:{port}", user, pwd
        return None
    # IPv4: ip:port or ip:port:user:pass
    parts = line.split(":")
    if len(parts) == 2 or len(parts) == 4:
        ip, port = parts[0], parts[1]
        try:
            ipaddress.ip_address(ip)
            if port.isdigit() and 1 <= int(port) <= 65535:
                if len(parts) == 4:
                    user, pwd = parts[2], parts[3]
                else:
                    user, pwd = None, None
                return f"{ip}:{port}", user, pwd
        except ValueError:
            return None
    return None

async def geo_lookup(ip, semaphore, retries=2):
    async with semaphore:
        for attempt in range(retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"http://ip-api.com/json/{ip}", timeout=3) as r:
                        if r.status == 200:
                            data = await r.json()
                            return {
                                "country": data.get("country", ""),
                                "region": data.get("regionName", ""),
                                "city": data.get("city", ""),
                                "org": data.get("org", "")
                            }
            except (aiohttp.ClientError, asyncio.TimeoutError, Exception):
                pass
            await asyncio.sleep(1)
    return {"country": "", "region": "", "city": "", "org": ""}

def ping_color(ms):
    if ms <= 100:
        return Fore.GREEN
    elif ms <= 300:
        return Fore.YELLOW
    return Fore.RED

async def write_result(proxy, result, fmt, outname, columns):
    output_file = f"{outname}.{fmt}"
    async with output_lock:
        try:
            if fmt == "txt":
                with open(output_file, "a") as f:
                    f.write(proxy + "\n")
            else:
                write_header = not os.path.isfile(output_file)
                with open(output_file, "a", newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=columns)
                    if write_header:
                        writer.writeheader()
                    row = {col: str(result.get(col, "")) for col in columns}
                    writer.writerow(row)
        except Exception as e:
            tqdm.write(Fore.RED + f"Error writing to {output_file}: {e}")

async def check_proxy(proxy, ptype, timeout, fmt, outname, columns, semaphore_geo, user=None, pwd=None):
    global working_count
    try:
        conn = aiohttp.TCPConnector(ssl=False)
        if user and pwd:
            proxy_url = f"{ptype}://{user}:{pwd}@{proxy}"
        else:
            proxy_url = f"{ptype}://{proxy}"
        async with aiohttp.ClientSession(connector=conn) as session:
            start = time.perf_counter()
            async with session.get("http://icanhazip.com", proxy=proxy_url, timeout=timeout) as resp:
                if resp.status == 200:
                    elapsed = int((time.perf_counter() - start) * 1000)
                    ip = proxy.split(":")[0].strip("[]")
                    geo = await geo_lookup(ip, semaphore_geo)
                    color = ping_color(elapsed)
                    working_count += 1
                    geo_info = f"{geo['country']}, {geo['city']}" if geo['country'] else "Unknown"
                    tqdm.write(color + f"{elapsed}ms {EMOJI_OK} {proxy} " +
                               f"{Fore.CYAN}({geo_info}) {Fore.MAGENTA}| Alive: {working_count}")
                    result = {
                        "proxy": proxy,
                        "ping": elapsed,
                        "country": geo["country"],
                        "region": geo["region"],
                        "city": geo["city"],
                        "org": geo["org"],
                        "user": user or "",
                        "pass": pwd or "",
                    }
                    await write_result(proxy, result, fmt, outname, columns)
    except Exception as e:
        tqdm.write(Fore.RED + f"Proxy check failed for {proxy}: {e}")

async def batch_runner(proxies, ptype, timeout, fmt, outname, columns, batch_size, geoip_limit):
    sem = asyncio.Semaphore(batch_size)
    geoip_semaphore = asyncio.Semaphore(geoip_limit)
    async def runner(proxy, user, pwd):
        async with sem:
            await check_proxy(proxy, ptype, timeout, fmt, outname, columns, geoip_semaphore, user, pwd)
    tasks = []
    for line in proxies:
        parsed = parse_proxy_line(line)
        if parsed:
            tasks.append(runner(*parsed))
    for f in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="🔍 Checking", colour="cyan"):
        try:
            await f
        except Exception as e:
            tqdm.write(Fore.RED + f"Error in batch task: {e}")

def get_columns(fmt):
    base = ["proxy", "ping", "country", "region", "city", "org"]
    extra = ["user", "pass"]
    try:
        pick = input(Fore.LIGHTCYAN_EX + f"Select output columns (comma separated, default: {','.join(base)}): ").strip()
        if pick:
            cols = [c.strip() for c in pick.split(",") if c.strip() in base + extra]
            return cols if cols else base
    except Exception:
        pass
    return base

def do_tests():
    print(Fore.YELLOW + "Running basic unit test...")
    test_lines = [
        "127.0.0.1:8080",
        "[2001:db8::1]:3128",
        "192.168.1.2:8080:usr:pwd",
        "[2001:db8::1]:3128:user:pass",
        "invalid:8080"
    ]
    for line in test_lines:
        res = parse_proxy_line(line)
        print(f"{line} => {res}")

def get_user_config():
    parser = argparse.ArgumentParser(description="Proxy Checker CLI")
    parser.add_argument('--file', default='proxy.txt')
    parser.add_argument('--type', default='socks5')
    parser.add_argument('--threads', type=int, default=100)
    parser.add_argument('--timeout', type=int, default=5)
    parser.add_argument('--format', default='txt')
    parser.add_argument('--out', default='nicenice')
    parser.add_argument('--test', action='store_true')
    parser.add_argument('--geoip-limit', type=int, default=45, help="GeoIP requests per minute (ip-api.com free tier)")
    args = parser.parse_args()
    allowed_types = ["http", "socks4", "socks5"]
    allowed_formats = ["txt", "csv"]
    if all(getattr(args, attr) == parser.get_default(attr) for attr in vars(args) if attr not in ['test', 'geoip_limit']):
        print(Style.BRIGHT + Fore.YELLOW + "─── Configuration ───" + Style.RESET_ALL)
        try:
            args.file = input(Fore.LIGHTCYAN_EX + "📄 Proxy file (ip:port): ").strip() or args.file
            args.type = input(Fore.LIGHTCYAN_EX + "🌐 Proxy type (http/socks4/socks5): ").strip().lower() or args.type
            args.threads = int(input(Fore.LIGHTCYAN_EX + "🧵 Threads: ").strip() or args.threads)
            args.timeout = int(input(Fore.LIGHTCYAN_EX + "⏱ Timeout (seconds): ").strip() or args.timeout)
            args.format = input(Fore.LIGHTCYAN_EX + "📤 Output format (txt/csv): ").strip().lower() or args.format
            args.out = input(Fore.LIGHTCYAN_EX + "💾 Output file name (no ext): ").strip() or args.out
        except Exception as e:
            print(Fore.RED + f"Error in interactive config: {e}")
            sys.exit(1)
        print("-" * 45)
    if args.type not in allowed_types:
        print(Fore.RED + f"Invalid proxy type: {args.type}")
        sys.exit(1)
    if args.format not in allowed_formats:
        print(Fore.RED + f"Invalid output format: {args.format}")
        sys.exit(1)
    return args

async def main():
    banner_slideshow(BANNER)
    args = get_user_config()
    if args.test:
        do_tests()
        return
    try:
        with open(args.file, "r") as f:
            raw = f.readlines()
    except FileNotFoundError:
        print(Fore.RED + "Proxy file not found.")
        return
    except Exception as e:
        print(Fore.RED + f"Error reading proxy file: {e}")
        return
    proxies = [line for line in raw if parse_proxy_line(line)]
    if not proxies:
        print(Fore.RED + "No valid proxies found.")
        return
    columns = get_columns(args.format)
    await batch_runner(proxies, args.type, args.timeout, args.format, args.out, columns, args.threads, args.geoip_limit)
    if working_count == 0:
        print(Fore.RED + "\nNo working proxies found.")
    else:
        print(Fore.YELLOW + f"\n✅ Done! {working_count} working proxies saved to {args.out}.{args.format}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
