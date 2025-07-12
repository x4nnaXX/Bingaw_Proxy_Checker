import os
import re
import csv
import aiohttp
import asyncio
import argparse
import sys
from colorama import Fore, Style, init
from tqdm.asyncio import tqdm_asyncio
from tqdm import tqdm

init(autoreset=True)
working_count = 0

def show_banner():
    os.system("cls" if os.name == "nt" else "clear")
    print(Fore.RED + r"""
 ██████╗ ██╗  ██╗██████╗ ██╗███╗   ██╗ ██████╗  █████╗ ██╗    ██╗
██╔═████╗╚██╗██╔╝██╔══██╗██║████╗  ██║██╔════╝ ██╔══██╗██║    ██║
██║██╔██║ ╚███╔╝ ██████╔╝██║██╔██╗ ██║██║  ███╗███████║██║ █╗ ██║
████╔╝██║ ██╔██╗ ██╔══██╗██║██║╚██╗██║██║   ██║██╔══██║██║███╗██║
╚██████╔╝██╔╝ ██╗██████╔╝██║██║ ╚████║╚██████╔╝██║  ██║╚███╔███╔╝
 ╚═════╝ ╚═╝  ╚═╝╚═════╝ ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝ ╚══╝╚══╝
""" + Fore.YELLOW + "   Multi-threaded Asynchronous Proxy Checker with GeoIP Lookup\n" + Style.RESET_ALL)

def supports_emoji():
    return sys.platform != "win32" or "WT_SESSION" in os.environ

EMOJI_OK = "✔" if supports_emoji() else "[OK]"
EMOJI_FAIL = "✘" if supports_emoji() else "[X]"

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

        print(Style.BRIGHT + Fore.LIGHTCYAN_EX + "📄 Proxy file (ip:port):", end=' ')
        args.file = input().strip() or args.file

        print(Style.BRIGHT + Fore.LIGHTCYAN_EX + "🌐 Proxy type (http/socks4/socks5):", end=' ')
        args.type = input().strip().lower() or args.type

        print(Style.BRIGHT + Fore.LIGHTCYAN_EX + "🧵 Threads:", end=' ')
        args.threads = int(input() or args.threads)

        print(Style.BRIGHT + Fore.LIGHTCYAN_EX + "⏱ Timeout (seconds):", end=' ')
        args.timeout = int(input() or args.timeout)

        print(Style.BRIGHT + Fore.LIGHTCYAN_EX + "📤 Output format (txt/csv):", end=' ')
        args.format = input().strip().lower() or args.format

        print(Style.BRIGHT + Fore.LIGHTCYAN_EX + "💾 Output file name (no ext):", end=' ')
        args.out = input().strip() or args.out
        print("-" * 45)

    if args.type not in allowed_types:
        print(Fore.RED + f"❌ Invalid proxy type '{args.type}'. Use: {', '.join(allowed_types)}")
        exit(1)
    if args.format not in allowed_formats:
        print(Fore.RED + f"❌ Invalid output format '{args.format}'. Use: txt or csv")
        exit(1)
    if args.threads <= 0 or args.timeout <= 0:
        print(Fore.RED + "❌ Threads and timeout must be positive integers.")
        exit(1)

    return args.file, args.type, args.threads, args.timeout, args.format, args.out

def validate_proxies(raw):
    print(Fore.YELLOW + "\n🔍 Validating Proxies...\n")
    regex = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}:\d{2,5}$")
    return [(i + 1, line.strip()) for i, line in enumerate(raw) if regex.match(line.strip())]

async def geo_lookup(ip):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://ip-api.com/json/{ip}", timeout=3) as resp:
                data = await resp.json()
                return {
                    "country": data.get("country", ""),
                    "region": data.get("regionName", ""),
                    "city": data.get("city", ""),
                    "org": data.get("org", "")
                }
    except:
        return {"country": "", "region": "", "city": "", "org": ""}

async def check_proxy(index, proxy, proxy_type, timeout):
    global working_count
    try:
        conn = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=conn) as session:
            proxy_url = f"{proxy_type}://{proxy}"
            async with session.get("http://httpbin.org/ip", proxy=proxy_url, timeout=timeout) as resp:
                if resp.status == 200:
                    geo = await geo_lookup(proxy.split(":")[0])
                    working_count += 1
                    tqdm.write(Fore.GREEN + f"[{index}] {EMOJI_OK} {proxy} ({geo['country']}, {geo['city']}) | Alive: {working_count}")
                    return {"proxy": proxy, **geo}
    except:
        pass
    return None

def save_output(results, fmt, name):
    with open(f"{name}.{fmt}", "w", newline='') as f:
        if fmt == "txt":
            for r in results:
                f.write(r["proxy"] + "\n")
        elif fmt == "csv":
            writer = csv.DictWriter(f, fieldnames=["proxy", "country", "region", "city", "org"])
            writer.writeheader()
            writer.writerows(results)

async def main():
    show_banner()
    file, ptype, threads, timeout, fmt, out_name = get_user_config()

    try:
        with open(file, "r") as f:
            raw = f.readlines()
    except FileNotFoundError:
        print(Fore.RED + f"❌ Proxy file '{file}' not found.")
        return

    proxies = validate_proxies(raw)
    if not proxies:
        print(Fore.RED + "❌ No valid proxies found.")
        return

    sem = asyncio.Semaphore(threads)
    results = []

    async def runner(idx, proxy):
        async with sem:
            return await check_proxy(idx, proxy, ptype, timeout)

    tasks = [runner(idx, px) for idx, px in proxies]
    for coro in tqdm_asyncio.as_completed(tasks, total=len(tasks), desc="🔍 Checking", colour="cyan"):
        result = await coro
        if result:
            results.append(result)

    save_output(results, fmt, out_name)
    print(Fore.YELLOW + f"\n✅ Done! {working_count} working proxies saved to {out_name}.{fmt}")

if __name__ == "__main__":
    asyncio.run(main())
