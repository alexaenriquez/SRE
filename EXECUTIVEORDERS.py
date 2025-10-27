#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor de Executive Orders (EO) de la Casa Blanca.
- Scrapea la lista de EO y detecta novedades.
- (Opcional) Cruza con Federal Register por título.
- Notifica por consola y/o via webhook POST.
Requisitos: requests, beautifulsoup4
Opcional: feedparser (si prefieres usar RSS en vez de HTML)

Env vars:
  WEBHOOK_URL         -> opcional (Slack/Discord/etc.)
  STATE_PATH          -> opcional (default: .eo_state.json)
  FR_CHECK            -> "1" para cruzar con Federal Register (default: "1")
  MAX_ITEMS           -> opcional, cuántos items leer (default: 20)

Uso local:
  pip install requests beautifulsoup4
  python watch_eo.py
"""

import json
import os
import re
import sys
import time
import html
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup

WHITEHOUSE_EO_URL = "https://www.whitehouse.gov/presidential-actions/executive-orders/"
WHITEHOUSE_PR_URL = "https://www.whitehouse.gov/presidential-actions/proclamations/"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "EO-Watcher/1.0 (+contact: you@example.com)"
})

def load_state(path: str) -> Dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}

def save_state(path: str, data: Dict):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def fetch_whitehouse_list(URL, max_items: int = 20) -> List[Dict]:
    """
    Devuelve una lista de EO con: { 'title', 'date', 'url', 'eo_number' }
    Nota: el DOM puede cambiar; se usan selectores relativamente robustos.
    """
    out = []
    r = SESSION.get(URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    cards = soup.select("article a[href]")
    if not cards:
        cards = soup.find_all("a", href=True)

    for a in cards:
        title = a.get_text(strip=True)
        href = a["href"]
        if href.startswith("/"):
            href = "https://www.whitehouse.gov" + href

        parent = a.find_parent("article")
        date = ""
        if parent:
            t = parent.find("time")
            if t:
                date = t.get("datetime") or t.get_text(strip=True)

        tipo = "Proclamation" if "proclamation" in URL else "Executive Order"

        if not title or not href:
            continue

        # 🔍 Detectar si es Executive Order o Proclamation
        if not re.search(r"\b(Executive Order|Proclamation)\b", title, flags=re.IGNORECASE):
            continue  # Ignorar otros tipos (como memoranda, fact sheets, etc.)
        
        m = re.search(r"\b(?:Executive Order\s*No\.?|EO|Proclamation(?:\s*No\.?)?)\s*([0-9\-]+)\b",
                      title, flags=re.IGNORECASE)
        eo_number = m.group(1) if m else None

        out.append({
            "title": title,
            "date": date,
            "url": href,
            "eo_number": eo_number,
            "tipo": tipo
        })

        if len(out) >= max_items:
            break

    return out


def notify(msg: str):
    print(msg)
    sys.stdout.flush()
    hook = os.getenv("WEBHOOK_URL", "").strip()
    if hook:
        try:
            SESSION.post(hook, json={"content": msg}, timeout=20)
        except Exception as e:
            print(f"[warn] Webhook error: {e}", file=sys.stderr)

def format_alert(item: Dict) -> str:
    parts = []
    tipo = item.get("tipo", "Acción presidencial")
    parts.append(f"🚨 Nueva {tipo} detectada")
    title = html.escape(item.get("title", ""))
    date = item.get("date", "")
    url = item.get("url", "")
    eo = item.get("eo_number") or "s/n"

    parts.append(f"• *Título:* {title}")
    parts.append(f"• *Fecha (WH):* {date}")
    parts.append(f"• *Número:* {eo}")
    parts.append(f"• *Enlace:* {url}")
    return "\n".join(parts)

def main():
    state_path = os.getenv("STATE_PATH", os.path.expanduser("~/eo_state.json"))
    max_items = int(os.getenv("MAX_ITEMS", "20"))
    fr_check = os.getenv("FR_CHECK", "1") == "1"

    state = load_state(state_path)
    last_seen_url = state.get("last_seen_url", "")

    items = fetch_whitehouse_list(URL=WHITEHOUSE_EO_URL, max_items=max_items)
    items += fetch_whitehouse_list(URL=WHITEHOUSE_PR_URL, max_items=max_items)

    if not items:
        print("[info] No se encontraron items en la lista (DOM pudo cambiar).")
        return

    # Detectar nuevos (del primero hacia atrás hasta llegar al último visto)
    new_items: List[Dict] = []
    for it in items:
        if it["url"] == last_seen_url:
            break
        new_items.append(it)

    if not new_items:
        print("[ok] Sin novedades.")
        return

    # Procesar en orden cronológico (del viejo al más nuevo)
    for it in reversed(new_items):
        msg = format_alert(it)
        notify(msg)
        time.sleep(1)  # pequeña pausa por si hay varios

    # Actualizar estado al más reciente de la lista
    state["last_seen_url"] = items[0]["url"]
    save_state(state_path, state)
    print("[done] Estado actualizado.")

if __name__ == "__main__":
    main()
