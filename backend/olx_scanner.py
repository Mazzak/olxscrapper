from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import requests
from bs4 import BeautifulSoup
import pandas as pd
from io import BytesIO
import re

app = FastAPI(title="OLX Price Scanner")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# ----------------------------
# Utils
# ----------------------------
def parse_price(text):
    if not text:
        return None, "N"

    negociavel = "negoci" in text.lower()
    clean = (
        text.lower()
        .replace("€", "")
        .replace("negociável", "")
        .replace("negociavel", "")
        .replace(".", "")
        .strip()
    )

    m = re.search(r"\d+", clean)
    price = int(m.group()) if m else None

    return price, "Y" if negociavel else "N"


# ----------------------------
# Core scanner (com dedupe)
# ----------------------------
def scan_olx(query, pages):
    results = []
    seen_links = set()

    for page in range(1, pages + 1):
        url = f"https://www.olx.pt/d/anuncios/q-{query}/?page={page}"

        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
        except requests.RequestException:
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        ads = soup.select("div[data-cy='l-card']")

        for ad in ads:
            a_tag = ad.find("a", href=True)
            if not a_tag:
                continue

            link = f"https://www.olx.pt{a_tag['href']}"
            if link in seen_links:
                continue
            seen_links.add(link)

            price_tag = ad.select_one("p[data-testid='ad-price']")
            if not price_tag:
                continue

            price, negociavel = parse_price(price_tag.text)
            if price is None:
                continue

            loc_tag = ad.select_one("p[data-testid='location-date']")
            localizacao, data = "", ""
            if loc_tag:
                parts = loc_tag.text.split("-", 1)
                localizacao = parts[0].strip()
                if len(parts) > 1:
                    data = parts[1].strip()

            results.append({
                "Preco": price,
                "Negociavel": negociavel,
                "Localizacao": localizacao,
                "Data": data,
                "Link": link
            })

    df = pd.DataFrame(results)

    return df


# ----------------------------
# API endpoints
# ----------------------------
@app.get("/scan")
def scan(
    query: str = Query(...),
    pages: int = Query(1, ge=1, le=25)
):
    df = scan_olx(query, pages)

    if df.empty:
        return {
            "stats": {"min": None, "max": None, "avg": None, "count": 0},
            "data": []
        }

    return {
        "stats": {
            "min": int(df["Preco"].min()),
            "max": int(df["Preco"].max()),
            "avg": round(df["Preco"].mean(), 2),
            "count": len(df)
        },
        "data": df.to_dict(orient="records")
    }


@app.get("/export/csv")
def export_csv(query: str, pages: int):
    df = scan_olx(query, pages)

    csv_text = df.to_csv(index=False, sep=";")

    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=olx_price_scanner.csv"
        }
    )


@app.get("/export/xls")
def export_xls(query: str, pages: int):
    df = scan_olx(query, pages)

    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return Response(
        content=output.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=olx_price_scanner.xlsx"
        }
    )
