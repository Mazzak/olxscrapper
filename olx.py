import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import requests
from bs4 import BeautifulSoup
import re
import csv
from statistics import mean
import webbrowser
from openpyxl import Workbook
import time
import json
import os

# Alertas (Windows)
try:
    import winsound
    HAS_WINSOUND = True
except Exception:
    HAS_WINSOUND = False

APP_TITLE = "OLX Price Scanner"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# ficheiros locais
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAV_FILE = os.path.join(BASE_DIR, "favorites.json")
SEEN_FILE = os.path.join(BASE_DIR, "seen_links.json")

ALL_ANUNCIOS = []   # resultados brutos da última pesquisa
LAST_QUERY_KEY = "" # chave da pesquisa actual (para vistos/novos)

# =========================
# PERSISTÊNCIA (JSON)
# =========================

def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        messagebox.showerror(APP_TITLE, f"Erro a gravar ficheiro:\n{path}\n\n{e}")

def load_favorites():
    return load_json(FAV_FILE, [])

def save_favorites(favs):
    save_json(FAV_FILE, favs)

def load_seen():
    # estrutura: { "query_key": ["link1","link2", ...] }
    return load_json(SEEN_FILE, {})

def save_seen(seen_map):
    save_json(SEEN_FILE, seen_map)

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

def ajustar_colunas(treeview):
    # limites (px)
    MIN_W = {"Preço": 90, "Negociável": 90, "Data": 140, "Localização": 180, "Link": 420, "Novo": 70}
    MAX_W = {"Preço": 140, "Negociável": 120, "Data": 260, "Localização": 360, "Link": 650, "Novo": 90}

    for col in treeview["columns"]:
        max_len = max([len(str(treeview.set(k, col))) for k in treeview.get_children()] + [len(col)])
        w = max_len * 8
        w = max(w, MIN_W.get(col, 100))
        w = min(w, MAX_W.get(col, 600))
        treeview.column(col, width=w)

def set_status(text):
    status_var.set(text)
    root.update_idletasks()

def set_progress(value, maximum=None):
    if maximum is not None:
        progress["maximum"] = maximum
    progress["value"] = value
    root.update_idletasks()

def beep_alert():
    if not var_alertas.get():
        return
    if HAS_WINSOUND:
        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass

def query_key(produto, min_price, max_price):
    # chave estável (não inclui páginas nem filtros)
    return f"{produto.strip().lower()}|{min_price}|{max_price}"

# =========================
# SCRAPING OLX
# =========================

def pesquisar_olx(query, min_price=0, max_price=9999, max_paginas=10, on_page_progress=None):
    resultados = []
    seen_links = set()

    for pagina in range(1, max_paginas + 1):
        if on_page_progress:
            on_page_progress(pagina)

        url = f"https://www.olx.pt/ads/q-{query}/?page={pagina}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
        except requests.RequestException:
            continue

        if r.status_code != 200:
            break

        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("div[data-cy='l-card']")
        if not cards:
            break

        for card in cards:
            a_tag = card.find("a", href=True)
            link = "https://www.olx.pt" + a_tag["href"] if a_tag else ""
            if not link or link in seen_links:
                continue
            seen_links.add(link)

            preco_tag = card.select_one("p[data-testid='ad-price']")
            preco = preco_tag.text.strip() if preco_tag else ""

            preco_num = extrair_preco(preco)
            if preco_num is None or preco_num < min_price or preco_num > max_price:
                continue

            negociavel = detectar_negociavel(preco)
            preco_limpo = (
                preco.replace("Negociável", "")
                     .replace("negociável", "")
                     .replace("negociavel", "")
                     .strip()
            )

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
                "localizacao": localizacao,
                "novo": "N"
            })

    return resultados

# =========================
# FILTROS (RESULTADOS)
# =========================

def passa_filtro_localizacao(localizacao: str, termo: str, modo: str) -> bool:
    loc = (localizacao or "").strip().lower()
    t = (termo or "").strip().lower()
    if not t:
        return True

    if modo == "Contém":
        return t in loc
    if modo == "Começa por":
        return loc.startswith(t)
    if modo == "Igual":
        return loc == t
    return True

def aplicar_filtros():
    if not ALL_ANUNCIOS:
        return

    filtrados = ALL_ANUNCIOS[:]

    # só negociáveis
    if var_negociavel.get():
        filtrados = [a for a in filtrados if a["negociavel"] == "Y"]

    # filtro localização
    termo_loc = entry_loc.get().strip()
    modo_loc = var_loc_mode.get()
    if termo_loc:
        filtrados = [a for a in filtrados if passa_filtro_localizacao(a.get("localizacao", ""), termo_loc, modo_loc)]

    # média com base no filtrado
    precos = [a["preco_num"] for a in filtrados if a["preco_num"]]
    preco_medio = mean(precos) if precos else None

    # só abaixo da média
    if var_abaixo_media.get() and preco_medio is not None:
        filtrados = [a for a in filtrados if a["preco_num"] <= preco_medio]
        precos = [a["preco_num"] for a in filtrados if a["preco_num"]]
        preco_medio = mean(precos) if precos else None

    # refrescar tabela principal
    for row in tree.get_children():
        tree.delete(row)

    new_count = 0
    for a in filtrados:
        row = tree.insert(
            "",
            tk.END,
            values=(a["link"], a["preco"], a["negociavel"], a["novo"], a["data"], a["localizacao"])
        )

        if a.get("novo") == "Y":
            tree.item(row, tags=("novo",))
            new_count += 1

        # highlight verde para <= média
        if preco_medio is not None and a["preco_num"] <= preco_medio:
            # se também for NOVO, mantém a cor NOVO (mais importante)
            if a.get("novo") != "Y":
                tree.item(row, tags=("bom_preco",))

    # stats reflectem filtrados
    if precos:
        lbl_stats.config(
            text=f"Preço mín: {min(precos)} € | Preço máx: {max(precos)} € | "
                 f"Preço médio: {int(preco_medio)} € | Anúncios: {len(filtrados)} | NOVOS: {new_count}"
        )
    else:
        lbl_stats.config(text=f"Sem preços válidos | Anúncios: {len(filtrados)} | NOVOS: {new_count}")

    ajustar_colunas(tree)
    set_status("Filtros aplicados ✅")

# =========================
# FAVORITOS
# =========================

def refresh_favorites_tab():
    favs = load_favorites()
    for row in fav_tree.get_children():
        fav_tree.delete(row)

    for f in favs:
        fav_tree.insert("", tk.END, values=(f["link"], f["preco"], f["negociavel"], f["data"], f["localizacao"]))

    ajustar_colunas(fav_tree)

def get_selected_row_values(treeview):
    item = treeview.focus()
    if not item:
        return None
    return treeview.item(item)["values"]

def add_selected_to_favorites():
    vals = get_selected_row_values(tree)
    if not vals:
        messagebox.showinfo(APP_TITLE, "Selecciona um anúncio na lista.")
        return

    link, preco, negociavel, novo, data, localizacao = vals

    favs = load_favorites()
    if any(f.get("link") == link for f in favs):
        set_status("Já está nos favoritos ⭐")
        return

    favs.append({
        "link": link,
        "preco": preco,
        "negociavel": negociavel,
        "data": data,
        "localizacao": localizacao,
        "added_at": time.strftime("%Y-%m-%d %H:%M:%S")
    })

    save_favorites(favs)
    refresh_favorites_tab()
    set_status("Adicionado aos favoritos ⭐")

def remove_selected_favorite():
    vals = get_selected_row_values(fav_tree)
    if not vals:
        messagebox.showinfo(APP_TITLE, "Selecciona um favorito.")
        return

    link = vals[0]
    favs = load_favorites()
    favs = [f for f in favs if f.get("link") != link]
    save_favorites(favs)
    refresh_favorites_tab()
    set_status("Favorito removido 🗑️")

def abrir_link_de_tree(treeview, event):
    item = treeview.identify_row(event.y)
    if item:
        link = treeview.item(item)["values"][0]
        webbrowser.open(link)

def copiar_link_tree(treeview):
    vals = get_selected_row_values(treeview)
    if not vals:
        return
    link = vals[0]
    root.clipboard_clear()
    root.clipboard_append(link)
    set_status("Link copiado 📋")

# =========================
# UI ACTIONS
# =========================

def bloquear_ui(is_running: bool):
    state = "disabled" if is_running else "normal"
    btn_pesquisar.config(state=state)
    btn_csv.config(state=state)
    btn_xlsx.config(state=state)

    entry_produto.config(state=state)
    entry_min.config(state=state)
    entry_max.config(state=state)
    entry_paginas.config(state=state)

    # filtros
    can_filter = (not is_running) and bool(ALL_ANUNCIOS)
    chk_negociavel.config(state="normal" if can_filter else "disabled")
    chk_abaixo_media.config(state="normal" if can_filter else "disabled")
    entry_loc.config(state="normal" if can_filter else "disabled")
    cmb_loc_mode.config(state="readonly" if can_filter else "disabled")

def buscar():
    global LAST_QUERY_KEY, ALL_ANUNCIOS

    produto = entry_produto.get().strip()
    if not produto:
        messagebox.showinfo(APP_TITLE, "Escreve um produto para pesquisar.")
        return

    try:
        min_price = int(entry_min.get())
        max_price = int(entry_max.get())
        max_pages = int(entry_paginas.get())
    except ValueError:
        messagebox.showerror(APP_TITLE, "Preços/Páginas inválidos (usa números).")
        return

    # reset filtros visuais
    var_negociavel.set(False)
    var_abaixo_media.set(False)
    var_loc_mode.set("Contém")
    entry_loc.delete(0, tk.END)

    for row in tree.get_children():
        tree.delete(row)

    lbl_stats.config(text="")
    set_status("A iniciar pesquisa…")
    set_progress(0, maximum=max_pages)
    bloquear_ui(True)

    start_time = time.perf_counter()

    # preparar seen/novos
    LAST_QUERY_KEY = query_key(produto, min_price, max_price)
    seen_map = load_seen()
    seen_set = set(seen_map.get(LAST_QUERY_KEY, []))

    def worker():
        nonlocal seen_map, seen_set
        try:
            def on_page(p):
                root.after(0, lambda: (set_status(f"A pesquisar página {p}/{max_pages}…"),
                                      set_progress(p)))

            anuncios = pesquisar_olx(produto, min_price, max_price, max_pages, on_page_progress=on_page)

            # marcar NOVOS e actualizar seen
            new_count = 0
            for a in anuncios:
                if a["link"] not in seen_set:
                    a["novo"] = "Y"
                    new_count += 1
                else:
                    a["novo"] = "N"

            # actualiza o visto (guarda todos os links encontrados agora)
            updated_seen = list(seen_set.union({a["link"] for a in anuncios}))
            seen_map[LAST_QUERY_KEY] = updated_seen
            save_seen(seen_map)

            # guardar resultados globais
            ALL_ANUNCIOS = anuncios

            elapsed = time.perf_counter() - start_time

            def update_ui():
                bloquear_ui(False)
                aplicar_filtros()
                refresh_favorites_tab()

                if new_count > 0:
                    beep_alert()
                    set_status(f"Pesquisa concluída ✅ ({elapsed:.1f}s) — {new_count} NOVO(s) 🔔")
                else:
                    set_status(f"Pesquisa concluída ✅ ({elapsed:.1f}s) — sem novos")

            root.after(0, update_ui)

        except Exception as e:
            def err():
                bloquear_ui(False)
                set_status("Erro na pesquisa ❌")
                messagebox.showerror(APP_TITLE, f"Erro: {e}")
            root.after(0, err)

    threading.Thread(target=worker, daemon=True).start()

# Sorting
sort_state = {"col": None, "reverse": False}

def ordenar_coluna(col):
    reverse = False
    if sort_state["col"] == col:
        reverse = not sort_state["reverse"]

    dados = []
    for k in tree.get_children(""):
        val = tree.set(k, col)
        if col == "Preço":
            n = extrair_preco(val) or 0
            dados.append((n, k))
        else:
            dados.append((val.lower(), k))

    dados.sort(reverse=reverse, key=lambda x: x[0])
    for i, (_, k) in enumerate(dados):
        tree.move(k, "", i)

    sort_state["col"] = col
    sort_state["reverse"] = reverse

def exportar_csv():
    path = filedialog.asksaveasfilename(defaultextension=".csv")
    if not path:
        return

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Link", "Preço", "Negociável", "Novo", "Data", "Localização"])
        for k in tree.get_children():
            writer.writerow(tree.item(k)["values"])

    messagebox.showinfo(APP_TITLE, "CSV exportado com sucesso ✅")

def exportar_xlsx():
    path = filedialog.asksaveasfilename(defaultextension=".xlsx")
    if not path:
        return

    wb = Workbook()
    ws = wb.active
    ws.title = APP_TITLE
    ws.append(["Link", "Preço", "Negociável", "Novo", "Data", "Localização"])

    for k in tree.get_children():
        ws.append(tree.item(k)["values"])

    for col in ws.columns:
        max_len = max(len(str(cell.value)) if cell.value else 0 for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 80)

    wb.save(path)
    messagebox.showinfo(APP_TITLE, "XLSX exportado com sucesso ✅")

# =========================
# UI
# =========================

root = tk.Tk()
root.title(APP_TITLE)
root.geometry("1180x760")

# Top inputs
frame_top = ttk.Frame(root)
frame_top.pack(fill=tk.X, padx=10, pady=6)

ttk.Label(frame_top, text="Produto").grid(row=0, column=0, sticky=tk.W)
entry_produto = ttk.Entry(frame_top, width=28)
entry_produto.grid(row=0, column=1, padx=6)

ttk.Label(frame_top, text="Preço mín").grid(row=0, column=2, sticky=tk.W)
entry_min = ttk.Entry(frame_top, width=7)
entry_min.insert(0, "0")
entry_min.grid(row=0, column=3, padx=6)

ttk.Label(frame_top, text="Preço máx").grid(row=0, column=4, sticky=tk.W)
entry_max = ttk.Entry(frame_top, width=7)
entry_max.insert(0, "9999")
entry_max.grid(row=0, column=5, padx=6)

ttk.Label(frame_top, text="Páginas").grid(row=0, column=6, sticky=tk.W)
entry_paginas = ttk.Entry(frame_top, width=5)
entry_paginas.insert(0, "10")
entry_paginas.grid(row=0, column=7, padx=6)

btn_pesquisar = ttk.Button(frame_top, text="Pesquisar", command=buscar)
btn_pesquisar.grid(row=0, column=8, padx=6)

btn_csv = ttk.Button(frame_top, text="Exportar CSV", command=exportar_csv)
btn_csv.grid(row=0, column=9, padx=6)

btn_xlsx = ttk.Button(frame_top, text="Exportar XLSX", command=exportar_xlsx)
btn_xlsx.grid(row=0, column=10, padx=6)

# Alertas + Favoritos
frame_actions = ttk.Frame(root)
frame_actions.pack(fill=tk.X, padx=10, pady=(0, 6))

var_alertas = tk.BooleanVar(value=True)
chk_alertas = ttk.Checkbutton(frame_actions, text="Alertar novos anúncios 🔔", variable=var_alertas)
chk_alertas.pack(side=tk.LEFT)

ttk.Button(frame_actions, text="⭐ Adicionar aos Favoritos", command=add_selected_to_favorites).pack(side=tk.LEFT, padx=12)

# Filters
frame_filters = ttk.Frame(root)
frame_filters.pack(fill=tk.X, padx=12, pady=(2, 0))

var_negociavel = tk.BooleanVar(value=False)
var_abaixo_media = tk.BooleanVar(value=False)

chk_negociavel = ttk.Checkbutton(frame_filters, text="Só negociáveis", variable=var_negociavel, command=aplicar_filtros)
chk_negociavel.pack(side=tk.LEFT, padx=(0, 12))

chk_abaixo_media = ttk.Checkbutton(frame_filters, text="Só abaixo da média", variable=var_abaixo_media, command=aplicar_filtros)
chk_abaixo_media.pack(side=tk.LEFT, padx=(0, 18))

ttk.Label(frame_filters, text="Localização:").pack(side=tk.LEFT)

var_loc_mode = tk.StringVar(value="Contém")
cmb_loc_mode = ttk.Combobox(frame_filters, textvariable=var_loc_mode, values=["Contém", "Começa por", "Igual"], width=12, state="disabled")
cmb_loc_mode.pack(side=tk.LEFT, padx=(8, 6))
cmb_loc_mode.bind("<<ComboboxSelected>>", lambda e: aplicar_filtros())

entry_loc = ttk.Entry(frame_filters, width=22, state="disabled")
entry_loc.pack(side=tk.LEFT, padx=6)
entry_loc.bind("<KeyRelease>", lambda e: aplicar_filtros())

chk_negociavel.config(state="disabled")
chk_abaixo_media.config(state="disabled")

# Stats
lbl_stats = ttk.Label(root, text="")
lbl_stats.pack(anchor=tk.W, padx=12)

# Progress + status
progress_frame = ttk.Frame(root)
progress_frame.pack(fill=tk.X, padx=12, pady=(6, 2))

progress = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate", length=340)
progress.pack(side=tk.LEFT)

status_var = tk.StringVar(value="Pronto.")
ttk.Label(progress_frame, textvariable=status_var).pack(side=tk.LEFT, padx=10)

# Notebook (Resultados + Favoritos)
notebook = ttk.Notebook(root)
notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

tab_results = ttk.Frame(notebook)
tab_favs = ttk.Frame(notebook)

notebook.add(tab_results, text="Resultados")
notebook.add(tab_favs, text="Favoritos")

# Results table
cols = ("Link", "Preço", "Negociável", "Novo", "Data", "Localização")
tree = ttk.Treeview(tab_results, columns=cols, show="headings")
for col in cols:
    tree.heading(col, text=col, command=lambda c=col: ordenar_coluna(c))
    tree.column(col, anchor=tk.W)
tree.tag_configure("bom_preco", background="#d4f4dd")
tree.tag_configure("novo", background="#fff3b0")  # amarelo suave
tree.pack(fill=tk.BOTH, expand=True)

tree.bind("<Double-1>", lambda e: abrir_link_de_tree(tree, e))

# Favorites table
fav_cols = ("Link", "Preço", "Negociável", "Data", "Localização")
fav_tree = ttk.Treeview(tab_favs, columns=fav_cols, show="headings")
for col in fav_cols:
    fav_tree.heading(col, text=col)
    fav_tree.column(col, anchor=tk.W)
fav_tree.pack(fill=tk.BOTH, expand=True)

fav_tree.bind("<Double-1>", lambda e: abrir_link_de_tree(fav_tree, e))

# Favorites remove button
fav_bottom = ttk.Frame(tab_favs)
fav_bottom.pack(fill=tk.X, pady=6)
ttk.Button(fav_bottom, text="🗑️ Remover dos Favoritos", command=remove_selected_favorite).pack(side=tk.LEFT)

# Shortcuts
def copiar_link_event(event=None):
    # copia do separador activo
    current = notebook.index(notebook.select())
    if current == 0:
        copiar_link_tree(tree)
    else:
        copiar_link_tree(fav_tree)

root.bind("<Control-c>", copiar_link_event)

# init favs
refresh_favorites_tab()

root.mainloop()