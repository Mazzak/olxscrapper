import tkinter as tk
from tkinter import ttk
import webbrowser
import requests
from bs4 import BeautifulSoup
import re
import time

BASE_URL = "https://www.olx.pt"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def extrair_preco(texto):
    if not texto: return None
    match = re.search(r'(\d+)', texto.replace('.', ''))
    return int(match.group(1)) if match else None

def pesquisar_olx(query, min_price=0, max_price=9999, max_paginas=10):
    anuncios = []
    for page in range(1, max_paginas + 1):
        url = f"{BASE_URL}/ads/q-{query.replace(' ', '-')}/?page={page}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
        except:
            continue
        cards = soup.select("div[data-cy='l-card']")
        if not cards: break
        for card in cards:
            link_tag = card.find("a", href=True)
            if not link_tag: continue

            # Preço
            preco_tag = card.select_one("p[data-testid='ad-price']")
            preco_str = preco_tag.text.strip() if preco_tag else "Sem preço"
            negociavel = "Y" if "negociável" in preco_str.lower() else "N"
            preco_limpo = preco_str.lower().replace("negociável", "").strip()
            preco_num = extrair_preco(preco_limpo)
            if preco_num is not None and (preco_num < min_price or preco_num > max_price):
                continue

            # Localização e Data (split pelo primeiro '-')
            loc_tag = card.select_one("p[data-testid='location-date']")
            localizacao = ""
            data = ""
            if loc_tag and loc_tag.text.strip():
                partes = loc_tag.text.split("-", 1)  # split na primeira ocorrência do "-"
                localizacao = partes[0].strip()
                if len(partes) > 1:
                    data = partes[1].strip()

            anuncios.append({
                "link": BASE_URL + link_tag["href"],
                "preco": preco_limpo,
                "data": data,
                "localizacao": localizacao
            })
        time.sleep(1)
    return anuncios

# ========================= GUI =========================

def abrir_link(event):
    item = tree.selection()[0]
    link = tree.item(item, "values")[0]
    webbrowser.open(link)

def ajustar_colunas():
    for col in cols:
        max_len = max([len(str(tree.set(child, col))) for child in tree.get_children()] + [len(col)])
        tree.column(col, width=max_len*8)

def buscar():
    for row in tree.get_children():
        tree.delete(row)
    query = entry_produto.get()
    try:
        min_price = int(entry_min.get())
        max_price = int(entry_max.get())
        max_pages = int(entry_paginas.get())
    except:
        return
    anuncios = pesquisar_olx(query, min_price, max_price, max_pages)
    for a in anuncios:
        tree.insert("", tk.END, values=(a["link"], a["preco"], a["data"], a["localizacao"]))
    ajustar_colunas()

# ========================= MAIN =========================

root = tk.Tk()
root.title("OLX Scraper 🛒")
root.geometry("1100x600")

frame_input = ttk.Frame(root)
frame_input.pack(padx=10, pady=5, fill=tk.X)

ttk.Label(frame_input, text="Produto:").grid(row=0, column=0, sticky=tk.W)
entry_produto = ttk.Entry(frame_input, width=30)
entry_produto.grid(row=0, column=1, padx=5)

ttk.Label(frame_input, text="Preço mínimo (€):").grid(row=1, column=0, sticky=tk.W)
entry_min = ttk.Entry(frame_input, width=10)
entry_min.grid(row=1, column=1, sticky=tk.W)

ttk.Label(frame_input, text="Preço máximo (€):").grid(row=2, column=0, sticky=tk.W)
entry_max = ttk.Entry(frame_input, width=10)
entry_max.grid(row=2, column=1, sticky=tk.W)

ttk.Label(frame_input, text="Máx páginas:").grid(row=3, column=0, sticky=tk.W)
entry_paginas = ttk.Entry(frame_input, width=10)
entry_paginas.grid(row=3, column=1, sticky=tk.W)
entry_paginas.insert(0, "10")  # default

ttk.Button(frame_input, text="Buscar 🔍", command=buscar).grid(row=0, column=2, rowspan=4, padx=10)

cols = ("Link", "Preço", "Data", "Localização")
tree = ttk.Treeview(root, columns=cols, show="headings")
for col in cols:
    tree.heading(col, text=col)
    tree.column(col, width=100)
tree.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
tree.bind("<Double-1>", abrir_link)

root.mainloop()
