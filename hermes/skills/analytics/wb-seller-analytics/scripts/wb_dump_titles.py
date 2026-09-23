#!/usr/bin/env python3
"""Dump all WB card titles (nmID, vendorCode, title, subject, brand, dims) to JSON.

Output: /root/.hermes/data/wb_all_titles.json
Used for: auditing titles for internal codes, color-in-title, missing sizes.

Usage:
    python3 scripts/wb_dump_titles.py

After dump, find 1C codes in titles with regex:
    \\b\\d{2}\\.\\d{2,3}([-_]\\w+)?\\b
"""
import json
import sys
import time

sys.path.insert(0, "/root/.hermes/scripts")
from wb_common import call_with_retry, mapping
from wb_mcp_client import WBMCPClient

OUT = "/root/.hermes/data/wb_all_titles.json"


def main():
    cards = []
    with WBMCPClient(timeout=280) as client:
        cursor = {"limit": 100}
        for page in range(40):
            result = call_with_retry(
                client, "wb_list_cards",
                {"settings": {"cursor": cursor, "filter": {"withPhoto": -1}}, "locale": "ru"},
                attempts=4,
            )
            batch = result.get("cards")
            if not isinstance(batch, list) or not batch:
                break
            for c in batch:
                c = mapping(c)
                dims = mapping(c.get("dimensions"))
                cards.append({
                    "nmID": c.get("nmID"),
                    "vendorCode": c.get("vendorCode"),
                    "title": c.get("title"),
                    "subjectName": c.get("subjectName"),
                    "brand": c.get("brand"),
                    "width": dims.get("width"),
                    "length": dims.get("length"),
                    "height": dims.get("height"),
                })
            cur = mapping(result.get("cursor"))
            if len(batch) < 100:
                break
            cursor = {"limit": 100, "updatedAt": cur.get("updatedAt"), "nmID": cur.get("nmID")}
            time.sleep(1)
            print("page %d: %d cards" % (page, len(cards)), file=sys.stderr)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, indent=1)
    print("TOTAL %d -> %s" % (len(cards), OUT))


if __name__ == "__main__":
    main()
