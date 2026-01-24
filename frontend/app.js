let table;

function setLoading(isLoading, msg) {
    const loading = document.getElementById("loading");
    const statusText = document.getElementById("statusText");
    const btnScan = document.getElementById("btnScan");
    const btnCsv = document.getElementById("btnCsv");
    const btnXls = document.getElementById("btnXls");

    if (msg) statusText.innerText = msg;

    if (isLoading) {
        loading.classList.remove("d-none");
        btnScan.disabled = true;
        btnCsv.disabled = true;
        btnXls.disabled = true;
    } else {
        loading.classList.add("d-none");
        btnScan.disabled = false;
    }
}

function scan() {
    const query = document.getElementById("query").value.trim();
    const pages = document.getElementById("pages").value;

    if (!query) return;

    setLoading(true, `A pesquisar "${query}" (${pages} páginas)…`);

    fetch(`http://127.0.0.1:8000/scan?query=${encodeURIComponent(query)}&pages=${pages}`)
        .then(r => r.json())
        .then(res => {

            document.getElementById("min").innerText = res.stats.min ?? "-";
            document.getElementById("max").innerText = res.stats.max ?? "-";
            document.getElementById("avg").innerText = res.stats.avg ?? "-";
            document.getElementById("count").innerText = res.stats.count ?? 0;

            if (table) table.destroy();

            table = $('#results').DataTable({
                data: res.data,
                columns: [
                    { data: "Preco" },
                    { data: "Negociavel" },
                    { data: "Data" },
                    { data: "Localizacao" },
                    {
                        data: "Link",
                        render: d => `<a href="${d}" target="_blank">Abrir</a>`
                    }
                ],
                order: [[0, "asc"]],
                autoWidth: true
            });

            document.getElementById("btnCsv").disabled = res.data.length === 0;
            document.getElementById("btnXls").disabled = res.data.length === 0;

            setLoading(false);
        })
        .catch(() => {
            setLoading(false, "Erro ao pesquisar.");
        });
}

function exportCsv() {
    const query = document.getElementById("query").value.trim();
    const pages = document.getElementById("pages").value;
    window.location.href =
        `http://127.0.0.1:8000/export/csv?query=${encodeURIComponent(query)}&pages=${pages}`;
}

function exportXls() {
    const query = document.getElementById("query").value.trim();
    const pages = document.getElementById("pages").value;
    window.location.href =
        `http://127.0.0.1:8000/export/xls?query=${encodeURIComponent(query)}&pages=${pages}`;
}
