"""
Coverage matrix — measure real-world extractor coverage.

Runs `extract_product_data` sequentially against a curated URL list and
prints a table showing, per site: final status, which tier did the work
(static httpx vs headless render), which fields were extracted, and timing.

Usage:
    python -m poc.coverage_matrix                    # uses poc/test_urls.txt
    python -m poc.coverage_matrix path/to/urls.txt
    python -m poc.coverage_matrix --delay 10         # gentler on sites
    python -m poc.coverage_matrix --label "VPN off"  # tag the run

YOUR IP DECIDES THE RESULT — label every run.
Anti-bot systems (Cloudflare, Akamai, PerimeterX) judge the IP's reputation
before they look at the request at all. The same URL list measured here:

    VPN off (residential IP) -> 10/11 ok   (Hollister returned its price)
    VPN on  (datacenter IP)  ->  6/11, the rest "blocked"

Same code, same URLs. So a run only means something next to the IP it came
from, and the two answer different questions:

    residential  ~= what a user's phone sees   (the Layer-0 WebView design)
    datacenter   ~= what a cloud server sees   (Railway/AWS in production)

A "blocked" row is a verdict on the IP, not on the scraper. Also avoid
re-running back-to-back: repeated hits burn even a good IP's reputation.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from poc.extractor import browser_manager, extract_product_data

DEFAULT_URLS_FILE = Path(__file__).parent / "test_urls.txt"
DEFAULT_DELAY_SECONDS = 3.0


def _load_urls(path: Path) -> list[str]:
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


async def main() -> None:
    # Avoid mojibake on the Windows console (cp1252 by default).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = sys.argv[1:]
    delay = DEFAULT_DELAY_SECONDS
    if "--delay" in args:
        idx = args.index("--delay")
        delay = float(args[idx + 1])
        del args[idx:idx + 2]

    label = None
    if "--label" in args:
        idx = args.index("--label")
        label = args[idx + 1]
        del args[idx:idx + 2]

    path = Path(args[0]) if args else DEFAULT_URLS_FILE
    if not path.exists():
        print(f"URL list not found: {path}")
        return
    urls = _load_urls(path)
    if not urls:
        print(f"No URLs found in {path}")
        return

    run_label = f"  [{label}]" if label else "  [unlabeled — which IP? VPN on/off?]"
    print(f"Coverage matrix — {len(urls)} URLs, {delay}s between{run_label}\n")
    header = (
        f"{'#':>2}  {'domain':<26} {'status':<12} {'tier':<9} "
        f"{'title':<6} {'price':>10} {'imgs':>4} {'sec':>6}"
    )
    print(header)
    print("-" * len(header))

    results: list[dict] = []
    try:
        for i, url in enumerate(urls, 1):
            # Space the requests out — a back-to-back burst is itself a bot tell.
            if i > 1 and delay:
                await asyncio.sleep(delay)
            start = time.perf_counter()
            try:
                data = await extract_product_data(url)
            except Exception as exc:
                # The extractor is designed not to raise; keep the run alive anyway.
                data = {
                    "status": "crash", "tier": "-", "title": None,
                    "price": None, "images": [],
                }
                print(f"    (crash: {type(exc).__name__}: {str(exc)[:80]})")
            elapsed = time.perf_counter() - start

            domain = urlparse(url).netloc.removeprefix("www.")[:26]
            title_mark = "yes" if data.get("title") else "-"
            price = data.get("price")
            price_str = f"{price:.2f}" if price is not None else "-"
            n_imgs = len(data.get("images") or [])
            print(
                f"{i:>2}  {domain:<26} {data.get('status', '?'):<12} "
                f"{data.get('tier', '?'):<9} {title_mark:<6} "
                f"{price_str:>10} {n_imgs:>4} {elapsed:>5.1f}s"
            )
            results.append(data)
    finally:
        await browser_manager.stop()

    # --- Summary ---
    total = len(results)
    ok = sum(1 for r in results if r.get("status") == "ok")
    blocked = sum(1 for r in results if r.get("status") == "blocked")
    no_data = sum(1 for r in results if r.get("status") == "no_data")
    fetch_err = sum(1 for r in results if r.get("status") == "fetch_error")
    rendered = sum(1 for r in results if r.get("tier") == "rendered")
    with_price = sum(1 for r in results if r.get("price") is not None)

    print("\nSummary")
    print(f"  ok:           {ok}/{total}")
    print(f"  blocked:      {blocked}/{total}   (anti-bot interstitial)")
    print(f"  no_data:      {no_data}/{total}   (page fetched, nothing usable)")
    print(f"  fetch_error:  {fetch_err}/{total}")
    print(f"  used render:  {rendered}/{total}")
    print(f"  got price:    {with_price}/{total}")
    if blocked:
        print(
            "\n  'blocked' judges the IP, not the scraper. A datacenter IP (VPN or\n"
            "  cloud server) gets challenged where a residential one walks through.\n"
            "  Compare against a run from the other kind of IP before concluding."
        )


if __name__ == "__main__":
    asyncio.run(main())
