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

DEFAULT_TEST_URLS = [
    "http://icanhazip.com",
    "http://www.google.com",
    "http://www.bing.com",
    "http://httpbin.org/ip"
]

def clear_terminal():
    try:
        os.system('cls' if os.name == 'nt' else 'clear')
    except Exception:
        pass

def get_term_width():
    try:
        return os.get_terminal_size().columns
    except Exception:
        return 80

def banner_slideshow(banner, slide_speed=0.05, hold_seconds=2, pause_seconds=1):
    lines = banner.strip('\n').split('\n')
    term_width = get_term_width()
    banner_width = max(len(line) for line in lines)
    space = max(0, term_width - banner_width)
    for pad in range(0, space + 1, 2):
        clear_terminal()
        for line in lines:
            print(' ' * pad + line)
        time.sleep(slide_speed)
    clear_terminal()
    for line in lines:
        print(' ' * (space // 2) + line)
    time.sleep(hold_seconds)
    clear_terminal()
    time.sleep(pause_seconds)

def parse_proxy_line(line):
    line = line.strip()
    if not line:
        return None
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
        except Exception:
            pass

async def check_proxy(proxy, ptype, timeout, fmt, outname, columns, test_urls, user=None, pwd=None, retries=2, pbar=None):
    global working_count
    for attempt in range(retries):
        for test_url in test_urls:
            try:
                conn = aiohttp.TCPConnector(ssl=False)
                if user and pwd:
                    proxy_url = f"{ptype}://{user}:{pwd}@{proxy}"
                else:
                    proxy_url = f"{ptype}://{proxy}"
                async with aiohttp.ClientSession(connector=conn) as session:
                    start = time.perf_counter()
                    async with session.get(test_url, proxy=proxy_url, timeout=timeout) as resp:
                        if resp.status == 200:
                            elapsed = int((time.perf_counter() - start) * 1000)
                            working_count += 1
                            result = {
                                "proxy": proxy,
                                "ping": elapsed,
                                "user": user or "",
                                "pass": pwd or "",
                                "test_url": test_url
                            }
                            await write_result(proxy, result, fmt, outname, columns)
                            # Only show alive proxies:
                            print(f"{Fore.GREEN}ALIVE: {proxy} | {test_url} | {elapsed}ms{Style.RESET_ALL}")
                            if pbar: pbar.refresh()  # keep progress bar at bottom
                            return
            except Exception:
                continue
        await asyncio.sleep(0.5)
    # Silent on failure

async def batch_runner(proxies, ptype, timeout, fmt, outname, columns, batch_size, test_urls, retries):
    sem = asyncio.Semaphore(batch_size)
    async def runner(proxy, user, pwd, pbar):
        async with sem:
            await check_proxy(proxy, ptype, timeout, fmt, outname, columns, test_urls, user, pwd, retries, pbar)
    tasks = []
    for line in proxies:
        parsed = parse_proxy_line(line)
        if parsed:
            tasks.append(parsed)
    total = len(tasks)
    with tqdm(total=total, desc="Proxy Checking", position=0, leave=True, ncols=80) as pbar:
        coros = [runner(*task, pbar) for task in tasks]
        for f in asyncio.as_completed(coros):
            try:
                await f
            except Exception:
                pass
            pbar.update(1)
            pbar.refresh()  # stick at bottom

def get_columns(fmt):
    base = ["proxy", "ping", "user", "pass", "test_url"]
    try:
        pick = input(Fore.LIGHTCYAN_EX +
                     f"Select output columns (comma separated, default: {','.join(base)}): ").strip()
        if pick:
            cols = [c.strip() for c in pick.split(",") if c.strip() in base]
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
    parser.add_argument('--retries', type=int, default=2)
    parser.add_argument('--test-urls', nargs='*', default=DEFAULT_TEST_URLS)
    args = parser.parse_args()
    allowed_types = ["http", "socks4", "socks5"]
    allowed_formats = ["txt", "csv"]
    if all(getattr(args, attr) == parser.get_default(attr) for attr in vars(args) if attr not in ['test', 'test_urls', 'retries']):
        print(Style.BRIGHT + Fore.YELLOW + "─── Configuration ───" + Style.RESET_ALL)
        try:
            args.file = input(Fore.LIGHTCYAN_EX + "📄 Proxy file (ip:port): ").strip() or args.file
            args.type = input(Fore.LIGHTCYAN_EX + "🌐 Proxy type (http/socks4/socks5): ").strip().lower() or args.type
            args.threads = int(input(Fore.LIGHTCYAN_EX + "🧵 Threads: ").strip() or args.threads)
            args.timeout = int(input(Fore.LIGHTCYAN_EX + "⏱ Timeout (seconds): ").strip() or args.timeout)
            args.format = input(Fore.LIGHTCYAN_EX + "📤 Output format (txt/csv): ").strip().lower() or args.format
            args.out = input(Fore.LIGHTCYAN_EX + "💾 Output file name (no ext): ").strip() or args.out
            custom_urls = input(Fore.LIGHTCYAN_EX + f"Test URLs (space separated, blank for default): ").strip()
            if custom_urls:
                args.test_urls = custom_urls.split()
            args.retries = int(input(Fore.LIGHTCYAN_EX + "🔁 Retries per proxy: ").strip() or args.retries)
        except Exception:
            sys.exit(1)
        print("-" * 45)
    if args.type not in allowed_types:
        sys.exit(1)
    if args.format not in allowed_formats:
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
    except Exception:
        print(Fore.RED + "Proxy file not found or unreadable.")
        return
    proxies = [line for line in raw if parse_proxy_line(line)]
    if not proxies:
        print(Fore.RED + "No valid proxies found.")
        return
    columns = get_columns(args.format)
    await batch_runner(proxies, args.type, args.timeout, args.format, args.out, columns, args.threads, args.test_urls, args.retries)
    print(Fore.YELLOW + f"\nDone! {working_count} working proxies saved to {args.out}.{args.format}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
