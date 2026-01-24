import tkinter as tk
from tkinter import ttk, filedialog
import requests
from bs4 import BeautifulSoup
import re
import csv
from statistics import mean
import webbrowser
from openpyxl import Workbook

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# =========================
# UTILITÁRIOS
# =========================

def extrair_preco(texto):
    if not texto:
        return None
    texto = texto.lower().replace("negociável", "").replace("negociavel", "")
    m = re.search(r'(\d+)', texto.replace('.', ''))
    return int(m.group(1)) if m else None


def detectar_negociavel(texto):
    if not texto:
        return "N"
    return "Y" if "negoci" in texto.lower() else "N"


def ajustar_colunas():
    for col in tree["columns"]:
        largura = max(
            [len(str(tree.set(k, col))) for k in tree.get_children()] + [len(col)]
        ) * 8
        tree.column(col, width=largura)


# =========================
# SCRAPING OLX
# =========================

def pesquisar_olx(query, min_price=0, max_price=9999, max_paginas=10):
    resultados = []

    for pagina in range(1, max_paginas + 1):
        url = f"https://www.olx.pt/ads/q-{query}/?page={pagina}"
        r = requests.get(url, headers=HEADERS, timeout=10)

        if r.status_code != 200:
            break

        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("div[data-cy='l-card']")

        if not cards:
            break

        for card in cards:
            a_tag = card.find("a", href=True)
            link = "https://www.olx.pt" + a_tag["href"] if a_tag else ""

            preco_tag = card.select_one("p[data-testid='ad-price']")
            preco = preco_tag.text.strip() if preco_tag else ""

            preco_num = extrair_preco(preco)
            if preco_num is None or preco_num < min_price or preco_num > max_price:
                continue

            negociavel = detectar_negociavel(preco)
            preco_limpo = preco.replace("Negociável", "").replace("negociável", "").strip()

            loc_tag = card.select_one("p[data-testid='location-date']")
            localizacao, data = "", ""
            if loc_tag:
                partes = loc_tag.text.split("-", 1)
                localizacao = partes[0].strip()
                if len(partes) > 1:
                    data = partes[1].strip()

            resultados.append({
                "link": link,
                "preco": preco_limpo,
                "preco_num": preco_num,
                "negociavel": negociavel,
                "data": data,
                "localizacao": localizacao
            })

    return resultados


# =========================
# UI ACTIONS
# =========================

def buscar():
    for row in tree.get_children():
        tree.delete(row)

    query = entry_produto.get().strip()
    if not query:
        return

    try:
        min_price = int(entry_min.get())
        max_price = int(entry_max.get())
        max_pages = int(entry_paginas.get())
    except:
        return

    anuncios = pesquisar_olx(query, min_price, max_price, max_pages)
    precos = [a["preco_num"] for a in anuncios if a["preco_num"]]

    for a in anuncios:
        row = tree.insert(
            "",
            tk.END,
            values=(a["link"], a["preco"], a["negociavel"], a["data"], a["localizacao"])
        )

        if precos and a["preco_num"] <= mean(precos):
            tree.item(row, tags=("bom_preco",))

    if precos:
        lbl_stats.config(
            text=f"Preço mín: {min(precos)} € | Preço máx: {max(precos)} € | Preço médio: {int(mean(precos))} €"
        )
    else:
        lbl_stats.config(text="Sem preços válidos")

    ajustar_colunas()


def ordenar_coluna(col, reverse=False):
    dados = [(tree.set(k, col), k) for k in tree.get_children("")]

    if col == "Preço":
        def num(v):
            m = re.search(r'\d+', v)
            return int(m.group()) if m else 0
        dados.sort(key=lambda t: num(t[0]), reverse=reverse)
    else:
        dados.sort(key=lambda t: t[0], reverse=reverse)

    for i, (_, k) in enumerate(dados):
        tree.move(k, "", i)

    tree.heading(col, command=lambda: ordenar_coluna(col, not reverse))


def exportar_csv():
    path = filedialog.asksaveasfilename(defaultextension=".csv")
    if not path:
        return

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Link", "Preço", "Negociável", "Data", "Localização"])

        for k in tree.get_children():
            writer.writerow(tree.item(k)["values"])


def exportar_xlsx():
    path = filedialog.asksaveasfilename(defaultextension=".xlsx")
    if not path:
        return

    wb = Workbook()
    ws = wb.active
    ws.title = "OLX Price Scanner"

    ws.append(["Link", "Preço", "Negociável", "Data", "Localização"])

    for k in tree.get_children():
        ws.append(tree.item(k)["values"])

    for col in ws.columns:
        max_len = max(len(str(cell.value)) if cell.value else 0 for cell in col)
        ws.column_dimensions[col[0].column_letter].width = max_len + 2

    wb.save(path)


def abrir_link(event):
    item = tree.identify_row(event.y)
    if item:
        webbrowser.open(tree.item(item)["values"][0])


# =========================
# UI
# =========================

root = tk.Tk()
root.title("OLX Price Scanner")

frame_top = ttk.Frame(root)
frame_top.pack(fill=tk.X, padx=10, pady=5)

ttk.Label(frame_top, text="Produto").grid(row=0, column=0)
entry_produto = ttk.Entry(frame_top, width=25)
entry_produto.grid(row=0, column=1)

ttk.Label(frame_top, text="Preço mín").grid(row=0, column=2)
entry_min = ttk.Entry(frame_top, width=6)
entry_min.insert(0, "0")
entry_min.grid(row=0, column=3)

ttk.Label(frame_top, text="Preço máx").grid(row=0, column=4)
entry_max = ttk.Entry(frame_top, width=6)
entry_max.insert(0, "9999")
entry_max.grid(row=0, column=5)

ttk.Label(frame_top, text="Páginas").grid(row=0, column=6)
entry_paginas = ttk.Entry(frame_top, width=4)
entry_paginas.insert(0, "10")
entry_paginas.grid(row=0, column=7)

ttk.Button(frame_top, text="Pesquisar", command=buscar).grid(row=0, column=8, padx=5)
ttk.Button(frame_top, text="Exportar CSV", command=exportar_csv).grid(row=0, column=9)
ttk.Button(frame_top, text="Exportar XLSX", command=exportar_xlsx).grid(row=0, column=10)

lbl_stats = ttk.Label(root, text="")
lbl_stats.pack(anchor=tk.W, padx=10)

cols = ("Link", "Preço", "Negociável", "Data", "Localização")
tree = ttk.Treeview(root, columns=cols, show="headings")

for col in cols:
    tree.heading(col, text=col, command=lambda c=col: ordenar_coluna(c))
    tree.column(col, anchor=tk.W)

tree.tag_configure("bom_preco", background="#d4f4dd")

tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
tree.bind("<Double-1>", abrir_link)

root.mainloop()
