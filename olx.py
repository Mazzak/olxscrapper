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
from urllib.parse import quote

# Alertas (Windows)
try:
    import winsound
    HAS_WINSOUND = True
except Exception:
    HAS_WINSOUND = False

APP_TITLE = "OLX Price Scanner"
HEADERS = {"User-Agent": "Mozilla/5.0"}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAV_FILE = os.path.join(BASE_DIR, "favorites.json")
SEEN_FILE = os.path.join(BASE_DIR, "seen_links.json")

RESULT_COLS = ("Link", "Preço", "Negociável", "Novo", "Data", "Localização")
FAV_COLS = ("Link", "Preço", "Negociável", "Data", "Localização")

ALL_ANUNCIOS = []
LAST_QUERY_KEY = ""
LAST_SEARCH_PARAMS = None

# Lock para impedir que o botão "Pesquisar" fique "preso"
RUN_LOCK = threading.Lock()

AUTO_REFRESH_JOB = None
REFRESH_OPTIONS = {
    "Off": 0,
    "5 min": 5,
    "10 min": 10,
    "15 min": 15,
    "30 min": 30,
    "60 min": 60
}

SORT_RESULTS = {"col": None, "reverse": False}
SORT_FAVS = {"col": None, "reverse": False}


# =========================
# JSON
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
    return load_json(SEEN_FILE, {})  # {query_key: [links...]}

def save_seen(seen_map):
    save_json(SEEN_FILE, seen_map)


# =========================
# UTIL
# =========================

def now_hhmmss():
    return time.strftime("%H:%M:%S")

def normalize_query_for_olx(q: str) -> str:
    q = (q or "").strip()
    q = re.sub(r"\s+", "-", q)
    return quote(q, safe="-")

def extrair_preco(texto):
    if not texto:
        return None
    texto = texto.lower().replace("negociável", "").replace("negociavel", "")
    m = re.search(r"(\d+)", texto.replace(".", ""))
    return int(m.group(1)) if m else None

def detectar_negociavel(texto):
    if not texto:
        return "N"
    return "Y" if "negoci" in texto.lower() else "N"

def query_key(produto, min_price, max_price):
    return f"{produto.strip().lower()}|{min_price}|{max_price}"

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

def ajustar_colunas(treeview):
    MIN_W = {"Preço": 90, "Negociável": 90, "Data": 140, "Localização": 180, "Link": 420, "Novo": 70}
    MAX_W = {"Preço": 140, "Negociável": 120, "Data": 260, "Localização": 360, "Link": 650, "Novo": 90}

    for col in treeview["columns"]:
        max_len = max([len(str(treeview.set(k, col))) for k in treeview.get_children()] + [len(col)])
        w = max_len * 8
        w = max(w, MIN_W.get(col, 100))
        w = min(w, MAX_W.get(col, 650))
        treeview.column(col, width=w)


# =========================
# SCRAPE
# =========================

def pesquisar_olx(query, min_price=0, max_price=9999, max_paginas=10, only_negotiable=False, on_page_progress=None):
    resultados = []
    seen_links = set()
    qslug = normalize_query_for_olx(query)

    for pagina in range(1, max_paginas + 1):
        if on_page_progress:
            on_page_progress(pagina)

        url = f"https://www.olx.pt/ads/q-{qslug}/?page={pagina}"
        if only_negotiable:
            url += "&search[filter_float_negotiable]=1"

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
                "novo": "N",
                "data": data,
                "localizacao": localizacao
            })

    return resultados


# =========================
# FILTROS
# =========================

def passa_filtros_base(a) -> bool:
    if var_negociavel.get() and a.get("negociavel") != "Y":
        return False
    termo_loc = entry_loc.get().strip().lower()
    if termo_loc and termo_loc not in (a.get("localizacao") or "").lower():
        return False
    return True

def aplicar_filtros():
    if not ALL_ANUNCIOS:
        for row in tree.get_children():
            tree.delete(row)
        lbl_stats.config(text="")
        return [], None

    filtrados = [a for a in ALL_ANUNCIOS if passa_filtros_base(a)]
    precos = [a["preco_num"] for a in filtrados if a["preco_num"]]
    preco_medio = mean(precos) if precos else None

    if var_abaixo_media.get() and preco_medio is not None:
        filtrados = [a for a in filtrados if a["preco_num"] <= preco_medio]
        precos = [a["preco_num"] for a in filtrados if a["preco_num"]]
        preco_medio = mean(precos) if precos else None

    for row in tree.get_children():
        tree.delete(row)

    new_count = 0
    for a in filtrados:
        row = tree.insert("", tk.END, values=(a["link"], a["preco"], a["negociavel"], a["novo"], a["data"], a["localizacao"]))
        if a.get("novo") == "Y":
            tree.item(row, tags=("novo",))
            new_count += 1
        if preco_medio is not None and a["preco_num"] <= preco_medio and a.get("novo") != "Y":
            tree.item(row, tags=("bom_preco",))

    if precos:
        lbl_stats.config(
            text=f"Preço mín: {min(precos)} € | Preço máx: {max(precos)} € | "
                 f"Preço médio: {int(preco_medio)} € | Anúncios: {len(filtrados)} | NOVOS: {new_count}"
        )
    else:
        lbl_stats.config(text=f"Sem preços válidos | Anúncios: {len(filtrados)} | NOVOS: {new_count}")

    ajustar_colunas(tree)
    atualizar_setas_cabecalho_resultados()
    return filtrados, preco_medio

def contar_novos_dentro_do_filtro():
    if not ALL_ANUNCIOS:
        return 0

    base = [a for a in ALL_ANUNCIOS if passa_filtros_base(a)]
    precos = [a["preco_num"] for a in base if a["preco_num"]]
    media = mean(precos) if precos else None

    final = base
    if var_abaixo_media.get() and media is not None:
        final = [a for a in base if a["preco_num"] <= media]

    return sum(1 for a in final if a.get("novo") == "Y")


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
    atualizar_setas_cabecalho_favs()

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
    favs = [f for f in load_favorites() if f.get("link") != link]
    save_favorites(favs)
    refresh_favorites_tab()
    set_status("Favorito removido 🗑️")

def abrir_link_de_tree(treeview, event):
    item = treeview.identify_row(event.y)
    if item:
        link = treeview.item(item)["values"][0]
        webbrowser.open(link)


# =========================
# ORDENAÇÃO + SETAS ▲/▼
# =========================

def atualizar_setas_cabecalho_resultados():
    for c in RESULT_COLS:
        txt = c
        if SORT_RESULTS["col"] == c:
            txt = f"{c} {'▼' if SORT_RESULTS['reverse'] else '▲'}"
        tree.heading(c, text=txt)

def atualizar_setas_cabecalho_favs():
    for c in FAV_COLS:
        txt = c
        if SORT_FAVS["col"] == c:
            txt = f"{c} {'▼' if SORT_FAVS['reverse'] else '▲'}"
        fav_tree.heading(c, text=txt)

def ordenar_treeview(treeview, sort_state, col, is_results=True):
    reverse = False
    if sort_state["col"] == col:
        reverse = not sort_state["reverse"]

    dados = []
    for item in treeview.get_children():
        valor = treeview.set(item, col)

        if col == "Preço":
            dados.append((extrair_preco(valor) or 0, item))
        elif col == "Novo":
            dados.append((0 if valor == "Y" else 1, item))
        else:
            dados.append((valor.lower(), item))

    dados.sort(reverse=reverse, key=lambda x: x[0])
    for i, (_, item) in enumerate(dados):
        treeview.move(item, "", i)

    sort_state["col"] = col
    sort_state["reverse"] = reverse

    if is_results:
        atualizar_setas_cabecalho_resultados()
    else:
        atualizar_setas_cabecalho_favs()


# =========================
# AUTO-REFRESH
# =========================

def cancel_auto_refresh():
    global AUTO_REFRESH_JOB
    if AUTO_REFRESH_JOB is not None:
        try:
            root.after_cancel(AUTO_REFRESH_JOB)
        except Exception:
            pass
        AUTO_REFRESH_JOB = None

def schedule_next_refresh(minutes: int):
    global AUTO_REFRESH_JOB
    cancel_auto_refresh()
    if minutes <= 0:
        return
    AUTO_REFRESH_JOB = root.after(minutes * 60 * 1000, auto_refresh_tick)

def auto_refresh_tick():
    minutes = REFRESH_OPTIONS.get(var_refresh.get(), 0)
    if minutes <= 0:
        return

    if LAST_SEARCH_PARAMS:
        produto, min_price, max_price, max_pages = LAST_SEARCH_PARAMS
        run_search(produto, min_price, max_price, max_pages, is_auto=True)

    schedule_next_refresh(minutes)

def on_refresh_changed(event=None):
    minutes = REFRESH_OPTIONS.get(var_refresh.get(), 0)
    if minutes <= 0:
        cancel_auto_refresh()
        set_status(f"Auto-refresh: Off ({now_hhmmss()})")
        return
    schedule_next_refresh(minutes)
    set_status(f"Auto-refresh: a cada {minutes} min ✅ ({now_hhmmss()})")


# =========================
# PESQUISA (robusta)
# =========================

def set_controls_running(running: bool):
    state = "disabled" if running else "normal"
    btn_pesquisar.config(state=state)
    btn_csv.config(state=state)
    btn_xlsx.config(state=state)
    entry_produto.config(state=state)
    entry_min.config(state=state)
    entry_max.config(state=state)
    entry_paginas.config(state=state)

def run_search(produto, min_price, max_price, max_pages, is_auto=False):
    global LAST_QUERY_KEY, ALL_ANUNCIOS, LAST_SEARCH_PARAMS

    if not RUN_LOCK.acquire(blocking=False):
        set_status("Já estou a pesquisar… 🙂")
        return

    start_time = time.perf_counter()

    def worker():
        global LAST_QUERY_KEY, ALL_ANUNCIOS, LAST_SEARCH_PARAMS
        try:
            LAST_QUERY_KEY = query_key(produto, min_price, max_price)
            seen_map = load_seen()
            seen_set = set(seen_map.get(LAST_QUERY_KEY, []))

            only_neg = var_negociavel.get()

            def on_page(p):
                root.after(0, lambda: (set_status(f"A pesquisar página {p}/{max_pages}…"), set_progress(p)))

            anuncios = pesquisar_olx(produto, min_price, max_price, max_pages, only_negotiable=only_neg, on_page_progress=on_page)

            if not anuncios:
                elapsed = time.perf_counter() - start_time
                root.after(0, lambda: set_status(f"0 anúncios encontrados ❗ ({elapsed:.1f}s)"))
                return

            for a in anuncios:
                a["novo"] = "Y" if a["link"] not in seen_set else "N"

            seen_map[LAST_QUERY_KEY] = list(seen_set.union({a["link"] for a in anuncios}))
            save_seen(seen_map)

            ALL_ANUNCIOS = anuncios
            LAST_SEARCH_PARAMS = (produto, min_price, max_price, max_pages)

            elapsed = time.perf_counter() - start_time

            def update_ui():
                aplicar_filtros()
                refresh_favorites_tab()

                novos_no_filtro = contar_novos_dentro_do_filtro()
                if novos_no_filtro > 0:
                    beep_alert()
                    set_status(f"{'Auto-refresh' if is_auto else 'Pesquisa'} ✅ ({elapsed:.1f}s) — {novos_no_filtro} NOVO(s) no filtro 🔔 ({now_hhmmss()})")
                else:
                    set_status(f"{'Auto-refresh' if is_auto else 'Pesquisa'} ✅ ({elapsed:.1f}s) — sem novos no filtro ({now_hhmmss()})")

            root.after(0, update_ui)

        except Exception as e:
            root.after(0, lambda: messagebox.showerror(APP_TITLE, f"Erro: {e}"))
        finally:
            RUN_LOCK.release()
            root.after(0, lambda: set_controls_running(False))

    if not is_auto:
        set_controls_running(True)
        set_progress(0, maximum=max_pages)
        set_status("A iniciar pesquisa…")
    else:
        set_status(f"Auto-refresh a correr… ({now_hhmmss()})")

    threading.Thread(target=worker, daemon=True).start()

def buscar():
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

    run_search(produto, min_price, max_price, max_pages, is_auto=False)

def on_filters_changed(*_):
    if ALL_ANUNCIOS:
        aplicar_filtros()


# =========================
# EXPORT
# =========================

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
root.geometry("1240x800")

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

ttk.Label(frame_top, text="Auto-refresh").grid(row=0, column=11, sticky=tk.W, padx=(12, 0))
var_refresh = tk.StringVar(value="Off")
cmb_refresh = ttk.Combobox(frame_top, textvariable=var_refresh, values=list(REFRESH_OPTIONS.keys()), width=8, state="readonly")
cmb_refresh.grid(row=0, column=12, padx=6)
cmb_refresh.bind("<<ComboboxSelected>>", on_refresh_changed)

frame_actions = ttk.Frame(root)
frame_actions.pack(fill=tk.X, padx=10, pady=(0, 6))

var_alertas = tk.BooleanVar(value=True)
ttk.Checkbutton(frame_actions, text="Alertar novos anúncios 🔔", variable=var_alertas).pack(side=tk.LEFT)

ttk.Button(frame_actions, text="⭐ Adicionar aos Favoritos", command=add_selected_to_favorites).pack(side=tk.LEFT, padx=12)

frame_filters = ttk.Frame(root)
frame_filters.pack(fill=tk.X, padx=12, pady=(2, 0))

var_negociavel = tk.BooleanVar(value=False)
var_abaixo_media = tk.BooleanVar(value=False)

ttk.Checkbutton(frame_filters, text="Só negociáveis", variable=var_negociavel, command=on_filters_changed).pack(side=tk.LEFT, padx=(0, 12))
ttk.Checkbutton(frame_filters, text="Só abaixo da média", variable=var_abaixo_media, command=on_filters_changed).pack(side=tk.LEFT, padx=(0, 18))

ttk.Label(frame_filters, text="Localização contém:").pack(side=tk.LEFT)
entry_loc = ttk.Entry(frame_filters, width=22)
entry_loc.pack(side=tk.LEFT, padx=6)
entry_loc.bind("<KeyRelease>", lambda e: on_filters_changed())

lbl_stats = ttk.Label(root, text="")
lbl_stats.pack(anchor=tk.W, padx=12)

progress_frame = ttk.Frame(root)
progress_frame.pack(fill=tk.X, padx=12, pady=(6, 2))

progress = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate", length=380)
progress.pack(side=tk.LEFT)

status_var = tk.StringVar(value="Pronto.")
ttk.Label(progress_frame, textvariable=status_var).pack(side=tk.LEFT, padx=10)

# ✅ Notebook com abas em cima
notebook = ttk.Notebook(root)
notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

tab_results = ttk.Frame(notebook)
tab_favs = ttk.Frame(notebook)
notebook.add(tab_results, text="Resultados")
notebook.add(tab_favs, text="Favoritos")

tree = ttk.Treeview(tab_results, columns=RESULT_COLS, show="headings")
for col in RESULT_COLS:
    tree.heading(col, text=col, command=lambda c=col: ordenar_treeview(tree, SORT_RESULTS, c, is_results=True))
    tree.column(col, anchor=tk.W)
tree.tag_configure("bom_preco", background="#d4f4dd")
tree.tag_configure("novo", background="#fff3b0")
tree.pack(fill=tk.BOTH, expand=True)
tree.bind("<Double-1>", lambda e: abrir_link_de_tree(tree, e))

fav_tree = ttk.Treeview(tab_favs, columns=FAV_COLS, show="headings")
for col in FAV_COLS:
    fav_tree.heading(col, text=col, command=lambda c=col: ordenar_treeview(fav_tree, SORT_FAVS, c, is_results=False))
    fav_tree.column(col, anchor=tk.W)
fav_tree.pack(fill=tk.BOTH, expand=True)
fav_tree.bind("<Double-1>", lambda e: abrir_link_de_tree(fav_tree, e))

fav_bottom = ttk.Frame(tab_favs)
fav_bottom.pack(fill=tk.X, pady=6)
ttk.Button(fav_bottom, text="🗑️ Remover dos Favoritos", command=remove_selected_favorite).pack(side=tk.LEFT)

# init
refresh_favorites_tab()
atualizar_setas_cabecalho_resultados()
atualizar_setas_cabecalho_favs()

root.mainloop()