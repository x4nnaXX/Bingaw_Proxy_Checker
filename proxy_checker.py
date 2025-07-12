import os
import re
import csv
import aiohttp
import asyncio
import argparse
import sys
import time
from colorama import Fore, Style, init
from tqdm.asyncio import tqdm_asyncio
from tqdm import tqdm

init(autoreset=True)
working_count = 0
output_lock = asyncio.Lock()

def show_banner():
    os.system("cls" if os.name == "nt" else "clear")
    print(Fore.RED + r"""
 ██████╗ ██╗  ██╗██████╗ ██╗███╗   ██╗ ██████╗  █████╗ ██╗    ██╗
██╔═████╗╚██╗██╔╝██╔══██╗██║████╗  ██║██╔════╝ ██╔══██╗██║    ██║
██║██╔██║ ╚███╔╝ ██████╔╝██║██╔██╗ ██║██║  ███╗███████║██║ █╗ ██║
████╔╝██║ ██╔██╗ ██╔══██╗██║██║╚██╗██║██║   ██║██╔══██║██║███╗██║
╚██████╔╝██╔╝ ██╗██████╔╝██║██║ ╚████║╚██████╔╝██║  ██║╚███╔███╔╝
 ╚═════╝ ╚═╝  ╚═╝╚═════╝ ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝ ╚══╝╚══╝
""" + Fore.YELLOW + "   Multi-threaded Asynchronous Proxy Checker with GeoIP & Ping\n" + Style.RESET_ALL)

def supports_emoji():
    return sys.platform != "win32" or "WT_SESSION" in os.environ

EMOJI_OK = "✔" if supports_emoji() else "[OK]"

def get_user_config():
    parser = argparse.ArgumentParser(description="Proxy Checker CLI")
    parser.add_argument('--file', default='proxy.txt')
    parser.add_argument('--type', default='socks5')
    parser.add_argument('--threads', type=int, default=100)
    parser.add_argument('--timeout', type=int, default=5)
    parser.add_argument('--format', default='txt')
    parser.add_argument('--out', default='nicenice')
    args = parser.parse_args()

    allowed_types = ["http", "socks4", "socks5"]
    allowed_formats = ["txt", "csv"]

    if all(getattr(args, attr) == parser.get_default(attr) for attr in vars(args)):
        print(Style.BRIGHT + Fore.YELLOW + "─── Configuration ───" + Style.RESET_ALL)
        args.file = input(Fore.LIGHTCYAN_EX + "📄 Proxy file (ip:port): ").strip() or args.file
        args.type = input(Fore.LIGHTCYAN_EX + "🌐 Proxy type (http/socks4/socks5): ").strip().lower() or args.type
        args.threads = int(input(Fore.LIGHTCYAN_EX + "🧵 Threads: ").strip() or args.threads)
        args.timeout = int(input(Fore.LIGHTCYAN_EX + "⏱ Timeout (seconds): ").strip() or args.timeout)
        args.format = input(Fore.LIGHTCYAN_EX + "📤 Output format (txt/csv): ").strip().lower() or args.format
        args.out = input(Fore.LIGHTCYAN_EX + "💾 Output file name (no ext): ").strip() or args.out
        print("-" * 45)

    if args.type not in allowed_types:
        print(Fore.RED + f"❌ Invalid proxy type '{args.type}'")
        exit(1)
    if args.format not in allowed_formats:
        print(Fore.RED + f"❌ Invalid output format '{args.format}'")
        exit(1)

    return args.file, args.type, args.threads, args.timeout, args.format, args.out

def validate_proxies(lines):
    print(Fore.YELLOW + "\n🔍 Validating Proxies...\n")
    regex = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}:\d{2,5}$")
    return [line.strip() for line in lines if regex.match(line.strip())]

async def geo_lookup(ip):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://ip-api.com/json/{ip}", timeout=3) as r:
                data = await r.json()
                return {
                    "country": data.get("country", ""),
                    "region": data.get("regionName", ""),
                    "city": data.get("city", ""),
                    "org": data.get("org", "")
                }
    except:
        return {"country": "", "region": "", "city": "", "org": ""}

def ping_color(ms):
    if ms <= 100:
        return Fore.GREEN
    elif ms <= 300:
        return Fore.YELLOW
    return Fore.RED

async def check_proxy(proxy, ptype, timeout, fmt, outname):
    global working_count
    try:
        conn = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=conn) as session:
            proxy_url = f"{ptype}://{proxy}"
            start = time.perf_counter()
            async with session.get("http://httpbin.org/ip", proxy=proxy_url, timeout=timeout) as resp:
                if resp.status == 200:
                    elapsed = int((time.perf_counter() - start) * 1000)
                    geo = await geo_lookup(proxy.split(":")[0])
                    color = ping_color(elapsed)
                    working_count += 1
                    geo_info = f"{geo['country']}, {geo['city']}" if geo['country'] else "Unknown"
                    tqdm.write(color + f"{elapsed}ms {EMOJI_OK} {proxy} " +
                               f"{Fore.CYAN}({geo_info}) {Fore.MAGENTA}| Alive: {working_count}")
                    async with output_lock:
                        with open(f"{outname}.{fmt}", "a", newline='') as f:
                            if fmt == "txt":
                                f.write(proxy + "\n")
                            else:
                                writer = csv.DictWriter(f, fieldnames=["proxy", "ping", "country", "region", "city", "org"])
                                if f.tell() == 0:
                                    writer.writeheader()
                                writer.writerow({
                                    "proxy": proxy,
                                    "ping": elapsed,
                                    "country": geo["country"],
                                    "region": geo["region"],
                                    "city": geo["city"],
                                    "org": geo["org"]
                                })
    except:
        pass

async def main():
    show_banner()
    file, ptype, threads, timeout, fmt, outname = get_user_config()
    try:
        with open(file, "r") as f:
            raw = f.readlines()
    except:
        print(Fore.RED + f"❌ Could not read file '{file}'")
        return

    proxies = validate_proxies(raw)
    if not proxies:
        print(Fore.RED + "❌ No valid proxies found.")
        return

    sem = asyncio.Semaphore(threads)

    async def runner(proxy):
        async with sem:
            await check_proxy(proxy, ptype, timeout, fmt, outname)

    tasks = [runner(p) for p in proxies]
    await tqdm_asyncio.gather(*tasks, total=len(tasks), desc="🔍 Checking", colour="cyan")

    print(Fore.YELLOW + f"\n✅ Done! {working_count} working proxies saved to {outname}.{fmt}")

if __name__ == "__main__":
    asyncio.run(main())
