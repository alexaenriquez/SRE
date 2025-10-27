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
    Devuelve una lista de EO o Proclamations con:
    { 'title', 'date', 'url', 'eo_number', 'tipo' }
    Adaptado al nuevo DOM de la Casa Blanca.
    """
    out = []
    r = SESSION.get(URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Seleccionar cada publicación
    posts = soup.select("div.wp-block-whitehouse-post-template__content")
    
    for post in posts:
        a = post.select_one(".wp-block-post-title a[href]")
        if not a:
            continue

        title = a.get_text(strip=True)
        href = a["href"]
        if href.startswith("/"):
            href = "https://www.whitehouse.gov" + href

        # Extraer fecha si existe
        t = post.select_one("time")
        date = t.get("datetime") if t else ""

        # Determinar tipo según URL
        tipo = "Proclamation" if "proclamation" in URL else "Executive Order"

        # Solo incluir si el título contiene EO o Proclamation
        m = re.search(
            r"\b(?:Executive Order\s*No\.?|EO|Proclamation(?:\s*No\.?)?)\s*([0-9\-]+)\b",
            title,
            flags=re.IGNORECASE
        )
        eo_number = m.group(1) if m else None
        if eo_number is None:
            continue  # saltar enlaces que no sean EO/Proclamation

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

    items = fetch_whitehouse_list(URL=WHITEHOUSE_EO_URL, max_items=max_items)
    items += fetch_whitehouse_list(URL=WHITEHOUSE_PR_URL, max_items=max_items)

    if not items:
        print("[info] No se encontraron items en la lista (DOM pudo cambiar).")
        return
    
    # Filtrar nuevos por tipo y mantener orden
    new_items: List[Dict] = []
    for tipo_key in ["Executive Order", "Proclamation"]:
        last_seen = state.get(tipo_key, "")
        tipo_items = [it for it in items if it["tipo"] == tipo_key]
        
        for it in tipo_items:
            if it["url"] == last_seen:
                break  # Detener solo para este tipo
            new_items.append(it)


    if not new_items:
        print("[ok] Sin novedades.")
        return

    # Procesar en orden cronológico (del viejo al más nuevo)
    for it in reversed(new_items):
        msg = format_alert(it)
        notify(msg)
        time.sleep(1)  # pequeña pausa por si hay varios

    # Guardar último visto por tipo
    for tipo_key in ["Executive Order", "Proclamation"]:
        tipo_new_items = [it for it in new_items if it["tipo"] == tipo_key]
        if tipo_new_items:
            state[tipo_key] = tipo_new_items[-1]["url"]  # el más reciente de este tipo


    save_state(state_path, state)
    print("[done] Estado actualizado.")

if __name__ == "__main__":
    main()
