import os
import sys
import time
import csv
import json
import aiohttp
import asyncio
import argparse
import ipaddress
from colorama import Fore, Style, init
from tqdm import tqdm
from aiohttp_socks import ProxyConnector, ProxyType

init(autoreset=True)
output_lock = asyncio.Lock()

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1393713235680563282/WH-HgOPhk7mBN2rFVY7FraNe39WPiqIoZIRIvwmhkCPM31iVIe9GHswI1WX4kJadYDDO"

BANNER_TXT = r"""
 ██████╗ ██╗  ██╗██████╗ ██╗███╗   ██╗ ██████╗  █████╗ ██╗    ██╗
██╔═████╗╚██╗██╔╝██╔══██╗██║████╗  ██║██╔════╝ ██╔══██╗██║    ██║
██║██╔██║ ╚███╔╝ ██████╔╝██║██╔██╗ ██║██║  ███╗███████║██║ █╗ ██║
████╔╝██║ ██╔██╗ ██╔══██╗██║██║╚██╗██║██║   ██║██╔══██║██║███╗██║
╚██████╔╝██╔╝ ██╗██████╔╝██║██║ ╚████║╚██████╔╝██║  ██║╚███╔███╔╝
 ╚═════╝ ╚═╝  ╚═╝╚═════╝ ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝ ╚══╝╚══╝
"""

DEFAULT_TEST_URLS = [
    "http://icanhazip.com",
    "http://httpbin.org/ip"
]
DEFAULT_LOG_FILE = "proxy_full_scan.log"

def print_banner_fixed():
    os.system('cls' if os.name == 'nt' else 'clear')
    print(Fore.RED + Style.BRIGHT + BANNER_TXT.center(os.get_terminal_size().columns))

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
                return f"[{ip}]:{port}"
        return None
    parts = line.split(":")
    if len(parts) == 2:
        ip, port = parts[0], parts[1]
        try:
            ipaddress.ip_address(ip)
            if port.isdigit() and 1 <= int(port) <= 65535:
                return f"{ip}:{port}"
        except ValueError:
            return None
    return None

def filter_proxies(raw_list):
    print(Fore.MAGENTA + Style.BRIGHT + "\nFiltering proxies..." + Style.RESET_ALL)
    time.sleep(1)
    filtered = []
    seen = set()
    for line in raw_list:
        p = parse_proxy_line(line)
        if p and p not in seen:
            filtered.append(p)
            seen.add(p)
    print(
        Fore.YELLOW + f"Total input: {len(raw_list)} | " +
        Fore.GREEN + f"Valid & unique: {len(filtered)}" + Style.RESET_ALL
    )
    print(Fore.LIGHTBLACK_EX + "Waiting 3 seconds before scanning..." + Style.RESET_ALL)
    time.sleep(3)
    return filtered

async def write_result(proxy, fmt, outname, extra=None):
    output_file = f"{outname}.{fmt}"
    async with output_lock:
        try:
            if fmt == "txt":
                with open(output_file, "a") as f:
                    f.write(proxy + "\n")
            elif fmt == "csv":
                with open(output_file, "a", newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([proxy] + (extra if extra else []))
            elif fmt == "json":
                with open(output_file, "a") as f:
                    data = {"proxy": proxy}
                    if extra: data.update(extra)
                    f.write(json.dumps(data) + "\n")
        except Exception:
            pass

async def write_full_log(proxy, status, reason, logfile=DEFAULT_LOG_FILE):
    async with output_lock:
        with open(logfile, "a") as f:
            row = {
                "proxy": proxy,
                "status": status,
                "reason": reason,
                "timestamp": int(time.time())
            }
            f.write(json.dumps(row) + "\n")

async def send_discord_webhook(proxy, ping, test_url, ptype, args_line, enabled=True):
    if not enabled:
        return
    content = (
        f"**ALIVE:** `{proxy}`\n"
        f"**Ping:** `{ping}ms`\n"
        f"**URL:** `{test_url}`\n"
        f"**Proxy Type:** `{ptype}`\n"
        f"**Args:** `{args_line}`"
    )
    data = {"content": content}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(DISCORD_WEBHOOK_URL, json=data) as resp:
                await resp.text()
    except Exception:
        pass

def ping_color(ms):
    if ms <= 100:
        return Fore.GREEN + Style.BRIGHT
    elif ms <= 300:
        return Fore.YELLOW + Style.BRIGHT
    return Fore.RED + Style.BRIGHT

async def test_http(proxy, test_urls, timeout):
    for url in test_urls:
        try:
            conn = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=conn) as session:
                start = time.perf_counter()
                async with session.get(url, proxy=f"http://{proxy}", timeout=timeout) as resp:
                    if resp.status == 200:
                        elapsed = int((time.perf_counter() - start) * 1000)
                        return True, elapsed, url, "http"
        except Exception:
            continue
    return False, None, None, "http"

async def test_socks4(proxy, test_urls, timeout):
    for url in test_urls:
        try:
            conn = ProxyConnector(proxy_type=ProxyType.SOCKS4, host=proxy.split(":")[0], port=int(proxy.split(":")[1]))
            async with aiohttp.ClientSession(connector=conn) as session:
                start = time.perf_counter()
                async with session.get(url, timeout=timeout) as resp:
                    if resp.status == 200:
                        elapsed = int((time.perf_counter() - start) * 1000)
                        return True, elapsed, url, "socks4"
        except Exception:
            continue
    return False, None, None, "socks4"

async def test_socks5(proxy, test_urls, timeout):
    for url in test_urls:
        try:
            conn = ProxyConnector(proxy_type=ProxyType.SOCKS5, host=proxy.split(":")[0], port=int(proxy.split(":")[1]))
            async with aiohttp.ClientSession(connector=conn) as session:
                start = time.perf_counter()
                async with session.get(url, timeout=timeout) as resp:
                    if resp.status == 200:
                        elapsed = int((time.perf_counter() - start) * 1000)
                        return True, elapsed, url, "socks5"
        except Exception:
            continue
    return False, None, None, "socks5"

async def check_proxy(proxy, ptype, timeout, fmt, outname, test_urls, pbar, retries, args_line, logall=True, discord_enabled=True):
    success, elapsed, used_url, detected_type = False, None, None, None
    reason = ""
    if ptype == "http":
        for _ in range(1 + retries):
            success, elapsed, used_url, _ = await test_http(proxy, test_urls, timeout)
            if success: break
        detected_type = "http"
    elif ptype == "socks4":
        for _ in range(1 + retries):
            success, elapsed, used_url, _ = await test_socks4(proxy, test_urls, timeout)
            if success: break
        detected_type = "socks4"
    elif ptype == "socks5":
        for _ in range(1 + retries):
            success, elapsed, used_url, _ = await test_socks5(proxy, test_urls, timeout)
            if success: break
        detected_type = "socks5"
    else:  # auto-detect
        for _ in range(1 + retries):
            for fn in (test_http, test_socks4, test_socks5):
                success, elapsed, used_url, detected_type = await fn(proxy, test_urls, timeout)
                if success: break
            if success: break
    if success:
        result_line = (
            Fore.MAGENTA + Style.BRIGHT + "ALIVE:" + Style.RESET_ALL + " " +
            Fore.CYAN + Style.BRIGHT + f"{proxy}" + Style.RESET_ALL + " " +
            ping_color(elapsed) + f"{elapsed}ms" + Style.RESET_ALL + " " +
            Fore.YELLOW + used_url + Style.RESET_ALL + " " +
            Fore.LIGHTGREEN_EX + f"[{detected_type}]" + Style.RESET_ALL
        )
        tqdm.write(result_line)
        await write_result(proxy, fmt, outname, [elapsed, used_url, detected_type])
        await send_discord_webhook(proxy, elapsed, used_url, detected_type, args_line, enabled=discord_enabled)
        if logall:
            await write_full_log(proxy, "ALIVE", f"{detected_type}:{elapsed}ms")
    else:
        if logall:
            await write_full_log(proxy, "DEAD", "Timeout or connection failed")
    pbar.update(1)

async def batch_runner(proxies, ptype, timeout, fmt, outname, threads, test_urls, retries, args_line, logall=True, discord_enabled=True):
    sem = asyncio.Semaphore(threads)
    total = len(proxies)
    with tqdm(total=total, desc=f"{Fore.YELLOW}{Style.BRIGHT}Checking Proxies{Style.RESET_ALL}", ncols=90, leave=True, position=1) as pbar:
        async def runner(proxy):
            async with sem:
                await check_proxy(proxy, ptype, timeout, fmt, outname, test_urls, pbar, retries, args_line, logall, discord_enabled)
        tasks = [runner(proxy) for proxy in proxies]
        await asyncio.gather(*tasks)
        pbar.close()

def numbered_select(options, prompt):
    for idx, val in enumerate(options):
        print(f" [{idx+1}] {val}")
    while True:
        try:
            sel = int(input(prompt + f" (1-{len(options)}): ").strip())
            if 1 <= sel <= len(options):
                return options[sel - 1]
        except Exception:
            print("Invalid input. Please enter a number.")

def get_user_config():
    parser = argparse.ArgumentParser(description="Proxy Checker CLI")
    parser.add_argument('--file', default='proxy.txt')
    parser.add_argument('--type', default='auto', help="Proxy type: http/socks4/socks5/auto")
    parser.add_argument('--threads', type=int, default=100)
    parser.add_argument('--timeout', type=int, default=5000, help="Timeout in milliseconds")
    parser.add_argument('--format', default='txt', help="txt/csv/json")
    parser.add_argument('--out', default='nicenice')
    parser.add_argument('--url', nargs='*', default=DEFAULT_TEST_URLS)
    parser.add_argument('--yes', action='store_true', help="Skip continue prompt after filtering")
    parser.add_argument('--retries', type=int, default=1)
    parser.add_argument('--no-discord', action='store_true', help="Disable Discord notifications")
    parser.add_argument('--resume', action='store_true', help="Resume from full scan log if exists")
    args = parser.parse_args()
    allowed_types = ["http", "socks4", "socks5", "auto"]
    allowed_formats = ["txt", "csv", "json"]
    yesno_opts = ["Yes", "No"]
    if all(getattr(args, attr) == parser.get_default(attr) for attr in vars(args) if attr not in ["yes", "retries", "no_discord", "resume"]):
        print(Fore.MAGENTA + Style.BRIGHT + "-" * 45 + Style.RESET_ALL)
        try:
            args.file = input(Fore.CYAN + Style.BRIGHT + "Proxy file (ip:port): " + Style.RESET_ALL).strip() or args.file
            args.type = numbered_select(allowed_types, "Select proxy type")
            args.threads = int(input(Fore.CYAN + Style.BRIGHT + "Threads: " + Style.RESET_ALL).strip() or args.threads)
            args.timeout = int(input(Fore.CYAN + Style.BRIGHT + "Timeout (ms): " + Style.RESET_ALL).strip() or args.timeout)
            args.format = numbered_select(allowed_formats, "Select output format")
            args.out = input(Fore.CYAN + Style.BRIGHT + "Output file name (no ext): " + Style.RESET_ALL).strip() or args.out
            urls = input(Fore.CYAN + Style.BRIGHT + "Test URLs (space-separated, blank for default): " + Style.RESET_ALL).strip()
            if urls:
                args.url = urls.split()
            args.retries = int(input(Fore.CYAN + Style.BRIGHT + "Retries per URL: " + Style.RESET_ALL).strip() or args.retries)
            args.no_discord = (numbered_select(yesno_opts, "Disable Discord notifications?") == "Yes")
            args.resume = (numbered_select(yesno_opts, "Resume from full scan log if exists?") == "Yes")
        except Exception:
            sys.exit(1)
        print(Fore.MAGENTA + Style.BRIGHT + "-" * 45 + Style.RESET_ALL)
    if args.type not in allowed_types:
        sys.exit(1)
    if args.format not in allowed_formats:
        sys.exit(1)
    return args

def get_args_line():
    return " ".join(sys.argv[1:]) or "(interactive mode)"

def load_resume_list(raw_list, logname=DEFAULT_LOG_FILE):
    checked = set()
    if os.path.exists(logname):
        with open(logname, "r") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    checked.add(obj.get("proxy"))
                except Exception:
                    continue
    return [proxy for proxy in raw_list if proxy not in checked]

async def main():
    args = get_user_config()
    args_line = get_args_line()
    try:
        with open(args.file, "r") as f:
            raw = f.readlines()
    except Exception:
        print(Fore.RED + "Proxy file not found or unreadable.")
        return
    proxies = filter_proxies(raw)
    if args.resume and os.path.exists(DEFAULT_LOG_FILE):
        proxies = load_resume_list(proxies, DEFAULT_LOG_FILE)
        print(Fore.YELLOW + f"Resuming, {len(proxies)} proxies left to check." + Style.RESET_ALL)
    if not args.yes:
        ans = input(Fore.CYAN + "Continue proxy checking? (y/n): " + Style.RESET_ALL).strip().lower()
        if ans != "y":
            print(Fore.RED + "Cancelled by user.")
            return
    if not proxies:
        print(Fore.RED + "No valid proxies found after filtering.")
        return
    await batch_runner(
        proxies, args.type, args.timeout / 1000, args.format, args.out, args.threads,
        args.url, args.retries, args_line,
        logall=True, discord_enabled=not args.no_discord
    )
    print(Fore.GREEN + Style.BRIGHT + f"\nDone! Working proxies saved to {args.out}.{args.format}" + Style.RESET_ALL)

if __name__ == "__main__":
    print_banner_fixed()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(Fore.RED + Style.BRIGHT + "\n\n[!] Scan cancelled by user (Ctrl+C)." + Style.RESET_ALL)
        print(Fore.YELLOW + "Partial results have been saved. Exiting cleanly.\n" + Style.RESET_ALL)
        sys.exit(0)
    except RuntimeError:
        loop = asyncio.get_event_loop()
        try:
            loop.run_until_complete(main())
        except KeyboardInterrupt:
            print(Fore.RED + Style.BRIGHT + "\n\n[!] Scan cancelled by user (Ctrl+C)." + Style.RESET_ALL)
            print(Fore.YELLOW + "Partial results have been saved. Exiting cleanly.\n" + Style.RESET_ALL)
            sys.exit(0)
