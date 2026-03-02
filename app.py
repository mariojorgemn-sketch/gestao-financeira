# app.py — Sistema de Gestão Financeira
# Streamlit Cloud + SQLite + pdfplumber (sem API key)

import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, datetime
from calendar import monthrange
import io
import re
import pdfplumber
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

# ══════════════════════════════════════════════════════════════
# CONFIGURAÇÃO DA PÁGINA
# ══════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Gestão Financeira",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .metric-card {
        background: white;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        text-align: center;
        margin-bottom: 10px;
    }
    .metric-label { color: #757575; font-size: 14px; margin-bottom: 4px; }
    .metric-value { font-size: 28px; font-weight: bold; }
    .receita-val  { color: #2E7D32; }
    .despesa-val  { color: #C62828; }
    .lucro        { color: #2E7D32; }
    .prejuizo     { color: #C62828; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# CATEGORIAS
# ══════════════════════════════════════════════════════════════

CATEGORIAS_RECEITA = ["Vendas", "Serviços", "Investimentos", "Comissões", "Outros"]
CATEGORIAS_DESPESA = ["Salários", "Aluguel", "Marketing", "Fornecedores",
                      "Utilidades", "Impostos", "Manutenção", "Outros"]

# ══════════════════════════════════════════════════════════════
# BASE DE DADOS
# ══════════════════════════════════════════════════════════════

DB = "financeiro.db"

def get_con():
    return sqlite3.connect(DB, check_same_thread=False)

def init_db():
    with get_con() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS receitas (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                descricao TEXT NOT NULL,
                categoria TEXT NOT NULL,
                valor     REAL NOT NULL,
                data      TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS despesas (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                descricao TEXT NOT NULL,
                categoria TEXT NOT NULL,
                valor     REAL NOT NULL,
                data      TEXT NOT NULL
            );
        """)

init_db()

def query(sql, params=()):
    with get_con() as c:
        return pd.read_sql_query(sql, c, params=params)

def execute(sql, params=()):
    with get_con() as c:
        c.execute(sql, params)
        c.commit()

def listar(tabela, ini=None, fim=None):
    if ini and fim:
        return query(
            f"SELECT * FROM {tabela} WHERE data BETWEEN ? AND ? ORDER BY data DESC",
            (ini, fim)
        )
    return query(f"SELECT * FROM {tabela} ORDER BY data DESC")

def inserir(tabela, descricao, categoria, valor, data):
    execute(
        f"INSERT INTO {tabela} (descricao,categoria,valor,data) VALUES (?,?,?,?)",
        (descricao, categoria, valor, data)
    )

def atualizar(tabela, id_, descricao, categoria, valor, data):
    execute(
        f"UPDATE {tabela} SET descricao=?,categoria=?,valor=?,data=? WHERE id=?",
        (descricao, categoria, valor, data, id_)
    )

def deletar(tabela, id_):
    execute(f"DELETE FROM {tabela} WHERE id=?", (id_,))

def calcular_totais(ini=None, fim=None):
    df_r = listar("receitas", ini, fim)
    df_d = listar("despesas", ini, fim)
    tr = float(df_r["valor"].sum()) if not df_r.empty else 0.0
    td = float(df_d["valor"].sum()) if not df_d.empty else 0.0
    return tr, td, tr - td

# ══════════════════════════════════════════════════════════════
# FORMATAÇÃO €
# ══════════════════════════════════════════════════════════════

def eur(valor):
    return f"{valor:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

# ══════════════════════════════════════════════════════════════
# EXPORTAR EXCEL
# ══════════════════════════════════════════════════════════════

def exportar_excel(ini=None, fim=None):
    wb = openpyxl.Workbook()
    cab = ["ID", "Data", "Descrição", "Categoria", "Valor (€)"]

    def estilizar(ws, cor):
        ws.append(cab)
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor=cor)
            cell.alignment = Alignment(horizontal="center")

    ws_r = wb.active
    ws_r.title = "Receitas"
    estilizar(ws_r, "2E7D32")
    for _, row in listar("receitas", ini, fim).iterrows():
        ws_r.append([row.id, row.data, row.descricao, row.categoria, row.valor])

    ws_d = wb.create_sheet("Despesas")
    estilizar(ws_d, "C62828")
    for _, row in listar("despesas", ini, fim).iterrows():
        ws_d.append([row.id, row.data, row.descricao, row.categoria, row.valor])

    tr, td, tl = calcular_totais(ini, fim)
    ws_s = wb.create_sheet("Resumo")
    ws_s.append(["Indicador", "Valor (€)"])
    ws_s.append(["Total Receitas", tr])
    ws_s.append(["Total Despesas", td])
    ws_s.append(["Lucro Líquido",  tl])

    for ws in [ws_r, ws_d, ws_s]:
        for col in ws.columns:
            w = max(len(str(c.value or "")) for c in col) + 4
            ws.column_dimensions[col[0].column_letter].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf

# ══════════════════════════════════════════════════════════════
# EXTRAÇÃO LOCAL DE PDF — pdfplumber (sem API, sem custos)
# ══════════════════════════════════════════════════════════════

def extrair_texto_pdf(pdf_bytes):
    texto = ""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pagina in pdf.pages:
            texto += (pagina.extract_text() or "") + "\n"
    return texto

def parsear_data(texto):
    padroes = [
        (r"\b(\d{4}-\d{2}-\d{2})\b",   "%Y-%m-%d"),
        (r"\b(\d{2}/\d{2}/\d{4})\b",   "%d/%m/%Y"),
        (r"\b(\d{2}-\d{2}-\d{4})\b",   "%d-%m-%Y"),
    ]
    for padrao, fmt in padroes:
        m = re.search(padrao, texto)
        if m:
            try:
                return datetime.strptime(m.group(1), fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass
    return str(date.today())

def parsear_valor(texto):
    padroes_total = [
        r"total\s+(?:a\s+pagar|geral|fatura)[\s:]*([0-9]+[.,][0-9]{2})",
        r"valor\s+total[\s:]*([0-9]+[.,][0-9]{2})",
        r"montante\s+total[\s:]*([0-9]+[.,][0-9]{2})",
        r"total[\s:]+([0-9]+[.,][0-9]{2})\s*€",
        r"([0-9]+[.,][0-9]{2})\s*€",
    ]
    for padrao in padroes_total:
        m = re.search(padrao, texto, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                pass
    todos = re.findall(r"\b(\d{1,6}[.,]\d{2})\b", texto)
    valores = []
    for v in todos:
        try:
            valores.append(float(v.replace(".", "").replace(",", ".")))
        except ValueError:
            pass
    return max(valores) if valores else 0.0

def inferir_categoria(texto):
    t = texto.lower()
    mapa = {
        "Salários":     ["salário","salario","vencimento","remuneração","recibo verde"],
        "Aluguel":      ["aluguer","aluguel","arrendamento","renda"],
        "Marketing":    ["marketing","publicidade","campanha","google ads","facebook"],
        "Fornecedores": ["fornecedor","material","mercadoria","produto","stock"],
        "Utilidades":   ["electricidade","eletricidade","água","agua","gás","gas",
                         "internet","telefone","edp","galp","nos","meo","vodafone"],
        "Impostos":     ["iva","imposto","taxa","irs","irc","segurança social"],
        "Manutenção":   ["manutenção","reparação","serviço técnico"],
    }
    for cat, palavras in mapa.items():
        for p in palavras:
            if p in t:
                return cat
    return "Outros"

def extrair_descricao(texto, nome_ficheiro):
    for linha in texto.split("\n"):
        linha = linha.strip()
        if any(k in linha.lower() for k in ["fatura nº","fatura n.","ref.","referência","documento"]):
            if len(linha) > 5:
                return linha[:80]
    return nome_ficheiro.replace(".pdf", "").replace("_", " ")

def analisar_pdf_local(pdf_bytes, nome_ficheiro):
    texto = extrair_texto_pdf(pdf_bytes)
    if not texto.strip():
        raise ValueError("PDF sem texto extraível. Pode ser uma imagem digitalizada.")

    # Tentar extrair linhas de extrato bancário (BPI, CGD, etc.)
    registos = []
    padrao_extrato = re.compile(
        r"(\d{2}[/-]\d{2}[/-]\d{4})\s+(.+?)\s+([-+]?\d{1,6}[.,]\d{2})\s*€?$",
        re.MULTILINE
    )
    for m in padrao_extrato.finditer(texto):
        try:
            d_str = m.group(1).replace("-", "/")
            d_obj = datetime.strptime(d_str, "%d/%m/%Y").strftime("%Y-%m-%d")
            desc  = m.group(2).strip()[:80]
            val   = float(m.group(3).replace(".", "").replace(",", "."))
            if val == 0:
                continue
            registos.append({
                "data":      d_obj,
                "descricao": desc,
                "categoria": inferir_categoria(desc),
                "valor":     abs(val),
                "_tipo":     "receita" if val > 0 else "despesa",
            })
        except ValueError:
            continue

    # Fallback: registo único com o total da fatura
    if not registos:
        registos = [{
            "data":      parsear_data(texto),
            "descricao": extrair_descricao(texto, nome_ficheiro),
            "categoria": inferir_categoria(texto),
            "valor":     parsear_valor(texto),
            "_tipo":     "despesa",
        }]

    return registos

# ══════════════════════════════════════════════════════════════
# SIDEBAR — NAVEGAÇÃO
# ══════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## 💼 Gestão Financeira")
    st.markdown("---")
    pagina = st.radio("", [
        "📊 Dashboard",
        "💰 Receitas",
        "💸 Despesas",
        "📂 Importar PDF",
        "📋 Relatório Mensal",
    ], label_visibility="collapsed")
    st.markdown("---")
    st.caption("Sistema de Gestão Financeira")

# ══════════════════════════════════════════════════════════════
# PÁGINA: DASHBOARD
# ══════════════════════════════════════════════════════════════

if pagina == "📊 Dashboard":
    st.title("📊 Dashboard")

    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        ini = st.date_input("De", value=date(date.today().year, 1, 1))
    with c2:
        fim = st.date_input("Até", value=date.today())
    with c3:
        st.markdown("<br>", unsafe_allow_html=True)
        exportar = st.button("⬇️ Exportar Excel", use_container_width=True)

    ini_str, fim_str = str(ini), str(fim)

    if exportar:
        buf = exportar_excel(ini_str, fim_str)
        st.download_button(
            label="📥 Descarregar Excel",
            data=buf,
            file_name=f"relatorio_{ini_str}_{fim_str}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    tr, td, tl = calcular_totais(ini_str, fim_str)
    cor_l  = "lucro" if tl >= 0 else "prejuizo"
    emoji_l = "📈" if tl >= 0 else "📉"

    m1, m2, m3 = st.columns(3)
    with m1:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-label">💰 Total de Receitas</div>
            <div class="metric-value receita-val">{eur(tr)}</div>
        </div>""", unsafe_allow_html=True)
    with m2:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-label">💸 Total de Despesas</div>
            <div class="metric-value despesa-val">{eur(td)}</div>
        </div>""", unsafe_allow_html=True)
    with m3:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-label">{emoji_l} Lucro Líquido</div>
            <div class="metric-value {cor_l}">{eur(tl)}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    col_g1, col_g2 = st.columns(2)

    with col_g1:
        fig = go.Figure(data=[
            go.Bar(name="Receitas", x=["Receitas"], y=[tr], marker_color="#2E7D32"),
            go.Bar(name="Despesas", x=["Despesas"], y=[td], marker_color="#C62828"),
            go.Bar(name="Lucro",    x=["Lucro"],    y=[abs(tl)],
                   marker_color="#1565C0" if tl >= 0 else "#E53935"),
        ])
        fig.update_layout(title="Receitas vs Despesas", showlegend=False,
                          plot_bgcolor="white", yaxis_tickprefix="€", height=350)
        st.plotly_chart(fig, use_container_width=True)

    with col_g2:
        df_d = listar("despesas", ini_str, fim_str)
        if not df_d.empty:
            cat_d = df_d.groupby("categoria")["valor"].sum().reset_index()
            fig2  = px.pie(cat_d, values="valor", names="categoria",
                           title="Despesas por Categoria",
                           color_discrete_sequence=px.colors.qualitative.Set3)
            fig2.update_layout(height=350)
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Sem despesas no período selecionado.")

    # Evolução mensal
    df_r = listar("receitas", ini_str, fim_str)
    df_d = listar("despesas", ini_str, fim_str)
    if not df_r.empty or not df_d.empty:
        def agrupar_mes(df, col):
            if df.empty:
                return pd.DataFrame(columns=["mes", col])
            df = df.copy()
            df["mes"] = df["data"].str[:7]
            return df.groupby("mes")["valor"].sum().reset_index().rename(columns={"valor": col})

        df_m = pd.merge(agrupar_mes(df_r, "receitas"),
                        agrupar_mes(df_d, "despesas"),
                        on="mes", how="outer").fillna(0).sort_values("mes")

        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=df_m["mes"], y=df_m.get("receitas", []),
                                   name="Receitas", line=dict(color="#2E7D32", width=2),
                                   fill="tozeroy", fillcolor="rgba(46,125,50,0.1)"))
        fig3.add_trace(go.Scatter(x=df_m["mes"], y=df_m.get("despesas", []),
                                   name="Despesas", line=dict(color="#C62828", width=2),
                                   fill="tozeroy", fillcolor="rgba(198,40,40,0.1)"))
        fig3.update_layout(title="Evolução Mensal", plot_bgcolor="white",
                           yaxis_tickprefix="€", height=300)
        st.plotly_chart(fig3, use_container_width=True)

# ══════════════════════════════════════════════════════════════
# PÁGINA: RECEITAS / DESPESAS
# ══════════════════════════════════════════════════════════════

elif pagina in ("💰 Receitas", "💸 Despesas"):
    tipo  = "receitas" if pagina == "💰 Receitas" else "despesas"
    cats  = CATEGORIAS_RECEITA if tipo == "receitas" else CATEGORIAS_DESPESA
    cls   = "receita-val" if tipo == "receitas" else "despesa-val"
    emoji = "💰" if tipo == "receitas" else "💸"

    st.title(f"{emoji} {tipo.capitalize()}")

    with st.expander("➕ Adicionar novo registo", expanded=False):
        with st.form(f"form_{tipo}", clear_on_submit=True):
            fc1, fc2, fc3, fc4 = st.columns([2, 3, 2, 2])
            with fc1: f_data = st.date_input("Data", value=date.today())
            with fc2: f_desc = st.text_input("Descrição")
            with fc3: f_cat  = st.selectbox("Categoria", cats)
            with fc4: f_val  = st.number_input("Valor (€)", min_value=0.0, step=0.01, format="%.2f")
            if st.form_submit_button("💾 Guardar", use_container_width=True):
                if not f_desc:
                    st.error("Descrição obrigatória.")
                elif f_val <= 0:
                    st.error("Valor tem de ser maior que zero.")
                else:
                    inserir(tipo, f_desc, f_cat, f_val, str(f_data))
                    st.success("Registo adicionado!")
                    st.rerun()

    st.markdown("#### 🔍 Filtrar por período")
    ff1, ff2, ff3 = st.columns([2, 2, 1])
    with ff1: f_ini = st.date_input("De",  value=date(date.today().year, 1, 1), key=f"ini_{tipo}")
    with ff2: f_fim = st.date_input("Até", value=date.today(), key=f"fim_{tipo}")
    with ff3:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Limpar", key=f"limpar_{tipo}"):
            st.rerun()

    df = listar(tipo, str(f_ini), str(f_fim))

    if df.empty:
        st.info("Nenhum registo encontrado.")
    else:
        total = df["valor"].sum()
        st.markdown(f"**Total no período: <span class='{cls}'>{eur(total)}</span>**",
                    unsafe_allow_html=True)
        st.markdown("---")

        for _, row in df.iterrows():
            ci, cv, ce, cd = st.columns([4, 2, 1, 1])
            with ci:
                st.markdown(f"**{row['descricao']}** · {row['categoria']} · {row['data']}")
            with cv:
                st.markdown(f"<span class='{cls}'><b>{eur(row['valor'])}</b></span>",
                            unsafe_allow_html=True)
            with ce:
                if st.button("✏️", key=f"ed_{tipo}_{row['id']}", help="Editar"):
                    st.session_state[f"editar_{tipo}"] = row.to_dict()
            with cd:
                if st.button("🗑️", key=f"del_{tipo}_{row['id']}", help="Eliminar"):
                    deletar(tipo, row["id"])
                    st.rerun()

        chave = f"editar_{tipo}"
        if chave in st.session_state and st.session_state[chave]:
            reg = st.session_state[chave]
            st.markdown("---")
            st.markdown("#### ✏️ Editar registo")
            with st.form(f"edit_{tipo}"):
                ec1, ec2, ec3, ec4 = st.columns([2, 3, 2, 2])
                with ec1:
                    e_data = st.date_input("Data",
                                           value=datetime.strptime(reg["data"], "%Y-%m-%d").date())
                with ec2:
                    e_desc = st.text_input("Descrição", value=reg["descricao"])
                with ec3:
                    idx   = cats.index(reg["categoria"]) if reg["categoria"] in cats else 0
                    e_cat = st.selectbox("Categoria", cats, index=idx)
                with ec4:
                    e_val = st.number_input("Valor (€)", value=float(reg["valor"]),
                                             min_value=0.0, step=0.01, format="%.2f")
                sc1, sc2 = st.columns(2)
                with sc1:
                    if st.form_submit_button("💾 Guardar", use_container_width=True):
                        atualizar(tipo, reg["id"], e_desc, e_cat, e_val, str(e_data))
                        del st.session_state[chave]
                        st.rerun()
                with sc2:
                    if st.form_submit_button("❌ Cancelar", use_container_width=True):
                        del st.session_state[chave]
                        st.rerun()

# ══════════════════════════════════════════════════════════════
# PÁGINA: IMPORTAR PDF
# ══════════════════════════════════════════════════════════════

elif pagina == "📂 Importar PDF":
    st.title("📂 Importar Faturas PDF")
    st.success("✅ Extração gratuita e local — sem necessidade de chave API.")

    ficheiros = st.file_uploader(
        "Seleciona uma ou mais faturas / extratos em PDF",
        type=["pdf"],
        accept_multiple_files=True
    )

    if ficheiros:
        st.markdown(f"**{len(ficheiros)} ficheiro(s) selecionado(s)**")

        if st.button("🔍 Extrair dados", use_container_width=True, type="primary"):
            todos = []
            barra = st.progress(0, text="A processar...")
            for i, f in enumerate(ficheiros):
                barra.progress(i / len(ficheiros), text=f"A processar: {f.name}...")
                try:
                    regs = analisar_pdf_local(f.read(), f.name)
                    for r in regs:
                        r["_ficheiro"]  = f.name
                        r["_confirmar"] = True
                        todos.append(r)
                except Exception as e:
                    st.error(f"Erro em '{f.name}': {e}")
            barra.progress(1.0, text="Concluído!")
            if todos:
                st.session_state["registos_pdf"] = todos
                st.success(f"✅ {len(todos)} registo(s) extraídos! Revê abaixo.")
            else:
                st.warning("Não foi possível extrair dados. O PDF pode ser uma imagem digitalizada.")

    if "registos_pdf" in st.session_state and st.session_state["registos_pdf"]:
        st.markdown("---")
        st.markdown("### 📋 Revê e confirma os registos")
        st.caption("Edita os campos se necessário. Marca ✔ os que queres guardar.")

        regs = st.session_state["registos_pdf"]
        atualizados = []

        h0,h1,h2,h3,h4,h5,h6 = st.columns([0.5,1.5,1,1.5,3,1.5,1.5])
        for h, t in zip([h0,h1,h2,h3,h4,h5,h6],
                        ["✔","Ficheiro","Tipo","Data","Descrição","Categoria","Valor (€)"]):
            h.markdown(f"**{t}**")
        st.divider()

        for i, reg in enumerate(regs):
            tipo_reg = reg.get("_tipo", "despesa")
            c0,c1,c2,c3,c4,c5,c6 = st.columns([0.5,1.5,1,1.5,3,1.5,1.5])

            with c0: confirmar = st.checkbox("", value=reg.get("_confirmar", True), key=f"chk_{i}")
            with c1: st.caption(reg.get("_ficheiro","")[:20])
            with c2:
                novo_tipo = st.selectbox("", ["despesa","receita"],
                                          index=0 if tipo_reg=="despesa" else 1,
                                          key=f"tipo_{i}", label_visibility="collapsed")
            with c3:
                try:
                    dv = datetime.strptime(reg.get("data", str(date.today())), "%Y-%m-%d").date()
                except Exception:
                    dv = date.today()
                nova_data = st.date_input("", value=dv, key=f"data_{i}",
                                           label_visibility="collapsed")
            with c4:
                nova_desc = st.text_input("", value=reg.get("descricao",""),
                                           key=f"desc_{i}", label_visibility="collapsed")
            with c5:
                cats_cur = CATEGORIAS_RECEITA if novo_tipo=="receita" else CATEGORIAS_DESPESA
                cat_val  = reg.get("categoria", cats_cur[0])
                if cat_val not in cats_cur: cat_val = cats_cur[0]
                nova_cat = st.selectbox("", cats_cur, index=cats_cur.index(cat_val),
                                         key=f"cat_{i}", label_visibility="collapsed")
            with c6:
                novo_val = st.number_input("", value=float(reg.get("valor",0)),
                                            min_value=0.0, step=0.01, format="%.2f",
                                            key=f"val_{i}", label_visibility="collapsed")
            st.divider()

            atualizados.append({
                "_ficheiro": reg.get("_ficheiro"),
                "_tipo":     novo_tipo,
                "_confirmar": confirmar,
                "data":      str(nova_data),
                "descricao": nova_desc,
                "categoria": nova_cat,
                "valor":     novo_val,
            })

        st.session_state["registos_pdf"] = atualizados
        confirmados = [r for r in atualizados if r["_confirmar"]]
        st.markdown(f"**{len(confirmados)} de {len(atualizados)} registos selecionados**")

        bc1, bc2 = st.columns(2)
        with bc1:
            if st.button("💾 Guardar confirmados", type="primary", use_container_width=True):
                for reg in confirmados:
                    tabela = "receitas" if reg["_tipo"] == "receita" else "despesas"
                    inserir(tabela, reg["descricao"], reg["categoria"],
                            reg["valor"], reg["data"])
                st.success(f"✅ {len(confirmados)} registo(s) guardados!")
                del st.session_state["registos_pdf"]
                st.rerun()
        with bc2:
            if st.button("🗑️ Limpar tudo", use_container_width=True):
                del st.session_state["registos_pdf"]
                st.rerun()

# ══════════════════════════════════════════════════════════════
# PÁGINA: RELATÓRIO MENSAL
# ══════════════════════════════════════════════════════════════

elif pagina == "📋 Relatório Mensal":
    st.title("📋 Relatório Mensal")

    rc1, rc2 = st.columns(2)
    with rc1:
        mes = st.selectbox("Mês", range(1,13), index=date.today().month-1,
                           format_func=lambda m: ["Janeiro","Fevereiro","Março","Abril",
                                                   "Maio","Junho","Julho","Agosto",
                                                   "Setembro","Outubro","Novembro","Dezembro"][m-1])
    with rc2:
        ano = st.number_input("Ano", min_value=2000, max_value=2100,
                               value=date.today().year, step=1)

    ultimo = monthrange(ano, mes)[1]
    ini_r  = f"{ano}-{mes:02d}-01"
    fim_r  = f"{ano}-{mes:02d}-{ultimo}"
    tr, td, tl = calcular_totais(ini_r, fim_r)
    cor_l  = "lucro" if tl >= 0 else "prejuizo"
    emoji_l = "📈" if tl >= 0 else "📉"

    st.markdown("---")
    m1, m2, m3 = st.columns(3)
    with m1:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-label">💰 Total Receitas</div>
            <div class="metric-value receita-val">{eur(tr)}</div>
        </div>""", unsafe_allow_html=True)
    with m2:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-label">💸 Total Despesas</div>
            <div class="metric-value despesa-val">{eur(td)}</div>
        </div>""", unsafe_allow_html=True)
    with m3:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-label">{emoji_l} Lucro Líquido</div>
            <div class="metric-value {cor_l}">{eur(tl)}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col_r, col_d = st.columns(2)

    with col_r:
        st.markdown("#### 💰 Receitas por categoria")
        df_r = listar("receitas", ini_r, fim_r)
        if not df_r.empty:
            for _, row in df_r.groupby("categoria")["valor"].sum().reset_index() \
                              .sort_values("valor", ascending=False).iterrows():
                cc1, cc2 = st.columns([3,2])
                cc1.markdown(f"• {row['categoria']}")
                cc2.markdown(f"<span class='receita-val'><b>{eur(row['valor'])}</b></span>",
                             unsafe_allow_html=True)
        else:
            st.info("Sem receitas neste mês.")

    with col_d:
        st.markdown("#### 💸 Despesas por categoria")
        df_d = listar("despesas", ini_r, fim_r)
        if not df_d.empty:
            for _, row in df_d.groupby("categoria")["valor"].sum().reset_index() \
                              .sort_values("valor", ascending=False).iterrows():
                dc1, dc2 = st.columns([3,2])
                dc1.markdown(f"• {row['categoria']}")
                dc2.markdown(f"<span class='despesa-val'><b>{eur(row['valor'])}</b></span>",
                             unsafe_allow_html=True)
        else:
            st.info("Sem despesas neste mês.")

    st.markdown("---")
    meses_pt = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
                "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
    buf = exportar_excel(ini_r, fim_r)
    st.download_button(
        label=f"⬇️ Exportar {meses_pt[mes-1]} {ano} para Excel",
        data=buf,
        file_name=f"relatorio_{meses_pt[mes-1]}_{ano}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
