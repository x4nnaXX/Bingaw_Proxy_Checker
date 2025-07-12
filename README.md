# Bingaw_Proxy_Checker
# Async Proxy Checker with GeoIP Lookup 🌍⚡

A fast and clean async proxy checker for `http`, `socks4`, and `socks5`, built with `aiohttp`. Features CLI flags, progress bar, real-time success count, and GeoIP info.

---

## ✅ Features

- Async proxy checking with `aiohttp`
- `http`, `socks4`, `socks5` support
- GeoIP lookup via `ip-api.com`
- Interactive or CLI flag-based config
- Real-time success counter (`Alive: N`)
- Output to `.txt` or `.csv`
- Tidy progress bar with `tqdm.write`
- Emoji fallback for unsupported terminals

---

## 📦 Install Requirements

```bash
pip install -r requirements.txt
```
---

## 🚀 Run

# Interactive Mode

```bash
python3 proxy_checker.py
```
# Command-line Mode

```bash
python3 proxy_checker.py --file proxy.txt --type http --threads 100 --timeout 5 --format csv --out good_proxies
```

## 🧩 Output Example

# TXT:
```bash
8.8.8.8:8080
1.1.1.1:3128
```
# CSV:
```bash
proxy,country,region,city,org
8.8.8.8:8080,US,California,Mountain View,Google
```

