import streamlit as st
import pandas as pd
import sqlite3
import os
import io
import re
from datetime import datetime, date
import xml.etree.ElementTree as ET

# Configuração da Página (Adaptada para Celular e Computador)
st.set_page_config(
    page_title="JJ Embalagens - Controle de Processos e Estoque",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Diretórios e Banco de Dados
DB_FILE = "estoque_jj.db"
CSV_INICIAL = "produtos_jj_embalagens.csv"
PASTA_FOTOS = "fotos_avarias"
SENHA_ZERAR = "6994"
os.makedirs(PASTA_FOTOS, exist_ok=True)

# Estilo Visual Orientado a Processos / Gestão à Vista (Kanban / Lean)
st.markdown("""
    <style>
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2rem;
    }
    .process-header {
        background: linear-gradient(90deg, #9E1B1B 0%, #781212 100%);
        color: white;
        padding: 15px 22px;
        border-radius: 10px;
        margin-bottom: 16px;
        border-left: 8px solid #F5B041;
        box-shadow: 0 3px 8px rgba(0,0,0,0.12);
    }
    .process-header h2 {
        margin: 0;
        font-size: 1.4rem;
        color: #FFFFFF !important;
        font-weight: 700;
    }
    .process-header p {
        margin: 4px 0 0 0;
        font-size: 0.9rem;
        color: #FADBD8;
    }
    .step-badge {
        background-color: #2C3E50;
        color: #F5B041;
        padding: 5px 12px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 0.85rem;
        display: inline-block;
        margin-bottom: 8px;
        letter-spacing: 0.5px;
    }
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
    }
    div[data-testid="stMetric"] {
        background-color: #FFFFFF;
        border: 1px solid #E5E8E8;
        border-left: 5px solid #9E1B1B;
        padding: 10px 14px;
        border-radius: 8px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    }
    div[data-testid="stMetricValue"] {
        color: #9E1B1B;
        font-weight: 700;
    }
    </style>
""", unsafe_allow_html=True)

# OTIMIZAÇÃO MÁXIMA DE ABERTURA: Conexão persistente em cache + WAL Mode
@st.cache_resource(show_spinner=False)
def obter_conexao():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_romaneio TEXT,
            data_registro TEXT,
            hora_registro TEXT,
            data_hora TEXT,
            tipo_operacao TEXT,
            motivo_destino TEXT,
            codigo_produto TEXT,
            cod_barras TEXT,
            descricao TEXT,
            grupo TEXT,
            quantidade REAL,
            unidade TEXT,
            responsavel TEXT,
            nf_numero TEXT,
            observacao TEXT,
            caminho_foto TEXT
        )
    """)
    
    cursor.execute("PRAGMA table_info(movimentacoes)")
    colunas_mov = [col[1] for col in cursor.fetchall()]
    if "data_registro" not in colunas_mov:
        cursor.execute("ALTER TABLE movimentacoes ADD COLUMN data_registro TEXT DEFAULT ''")
    if "hora_registro" not in colunas_mov:
        cursor.execute("ALTER TABLE movimentacoes ADD COLUMN hora_registro TEXT DEFAULT ''")
    if "grupo" not in colunas_mov:
        cursor.execute("ALTER TABLE movimentacoes ADD COLUMN grupo TEXT DEFAULT 'GERAL'")
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='produtos'")
    if not cursor.fetchone():
        if os.path.exists(CSV_INICIAL):
            df_init = pd.read_csv(
                CSV_INICIAL,
                dtype={'CODIGO': str, 'COD_BARRAS': str},
                low_memory=False
            )
            df_init['CODIGO'] = df_init['CODIGO'].astype(str).str.zfill(6)
            for col_extra, val_padrao in [
                ('ULTIMA_MOV_DATA', ''),
                ('ULTIMA_MOV_HORA', ''),
                ('ULTIMO_OPERADOR', '')
            ]:
                if col_extra not in df_init.columns:
                    df_init[col_extra] = val_padrao
            df_init.to_sql("produtos", conn, if_exists="replace", index=False, chunksize=1000)
    else:
        cursor.execute("PRAGMA table_info(produtos)")
        colunas_prod = [col[1] for col in cursor.fetchall()]
        for col_extra in ['ULTIMA_MOV_DATA', 'ULTIMA_MOV_HORA', 'ULTIMO_OPERADOR']:
            if col_extra not in colunas_prod:
                cursor.execute(f"ALTER TABLE produtos ADD COLUMN {col_extra} TEXT DEFAULT ''")
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prod_codigo ON produtos(CODIGO)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prod_ean ON produtos(COD_BARRAS)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prod_grupo ON produtos(GRUPO)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_mov_data ON movimentacoes(data_registro)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_mov_resp ON movimentacoes(responsavel)")
    
    conn.commit()
    return conn

conn_global = obter_conexao()

if "carrinho_saida" not in st.session_state:
    st.session_state.carrinho_saida = []
if "carrinho_entrada" not in st.session_state:
    st.session_state.carrinho_entrada = []

@st.cache_data(ttl=600, show_spinner=False)
def carregar_produtos():
    df = pd.read_sql("SELECT * FROM produtos", conn_global)
    for c in ["SALDO_DEPOSITO", "SALDO_LOJA", "ESTOQUE_MINIMO", "PRECO_VENDA"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
            
    for c_txt in ["CODIGO", "ULTIMA_MOV_DATA", "ULTIMA_MOV_HORA", "ULTIMO_OPERADOR", "COD_BARRAS", "DESCRICAO", "GRUPO", "UND_VENDA", "FORNECEDOR"]:
        if c_txt not in df.columns:
            df[c_txt] = ""
        else:
            df[c_txt] = df[c_txt].fillna("").astype(str)
            
    df["STATUS_ESTOQUE"] = "🟢 ESTOQUE CONFORTÁVEL"
    mask_alerta = (df["SALDO_DEPOSITO"] <= df["ESTOQUE_MINIMO"] * 1.25) & (df["SALDO_DEPOSITO"] >= df["ESTOQUE_MINIMO"])
    mask_abaixo = (df["SALDO_DEPOSITO"] < df["ESTOQUE_MINIMO"]) & (df["SALDO_DEPOSITO"] > 0)
    mask_ruptura = df["SALDO_DEPOSITO"] <= 0
    
    df.loc[mask_alerta, "STATUS_ESTOQUE"] = "🟠 ALERTA DE SEGURANÇA"
    df.loc[mask_abaixo, "STATUS_ESTOQUE"] = "🟡 ABAIXO DO MÍNIMO (REPOR)"
    df.loc[mask_ruptura, "STATUS_ESTOQUE"] = "🔴 RUPTURA / ZERADO"
    
    df["BUSCA_RAPIDA"] = (
        df["CODIGO"] + " | " +
        df["DESCRICAO"] + " | EAN: " +
        df["COD_BARRAS"] + " [Saldo: " +
        df["SALDO_DEPOSITO"].round(1).astype(str) + " " +
        df["UND_VENDA"] + " | Forn: " +
        df["FORNECEDOR"].str[:20] + "]"
    )
    return df

@st.cache_data(ttl=300, show_spinner=False)
def carregar_movimentacoes():
    return pd.read_sql("SELECT * FROM movimentacoes ORDER BY id DESC", conn_global)

def limpar_caches():
    carregar_produtos.clear()
    carregar_movimentacoes.clear()

@st.cache_data(show_spinner=False)
def gerar_excel_bytes(df_export, nome_aba="Relatorio_Estoque"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_export.to_excel(writer, index=False, sheet_name=nome_aba)
    return output.getvalue()

@st.cache_data(show_spinner=False)
def carregar_logo():
    if os.path.exists("logo.png"):
        with open("logo.png", "rb") as f:
            return f.read()
    return None

def extrair_itens_nf(arq_nf, df_catalogo):
    """Extrai itens tanto de XML padrão SEFAZ quanto de HTML de DANFE/ERP e identifica se já estão cadastrados."""
    nome_arq = arq_nf.name.lower()
    itens = []
    fornecedor_nf = "FORNECEDOR NF"
    numero_nf = arq_nf.name
    
    if nome_arq.endswith(".xml"):
        tree = ET.parse(arq_nf)
        root = tree.getroot()
        for elem in root.iter():
            tag_limpa = elem.tag.split("}")[-1]
            if tag_limpa == "emit":
                for sub in elem:
                    if sub.tag.split("}")[-1] == "xNome" and sub.text:
                        fornecedor_nf = sub.text.strip().upper()
            elif tag_limpa == "nNF" and elem.text:
                numero_nf = elem.text.strip()
            elif tag_limpa == "prod":
                cProd, cEAN, xProd, qCom, uCom = "", "", "", 0.0, "UN"
                for child in elem:
                    t = child.tag.split("}")[-1]
                    if t == "cProd": cProd = (child.text or "").strip()
                    elif t == "cEAN": cEAN = (child.text or "").strip()
                    elif t == "xProd": xProd = (child.text or "").strip().upper()
                    elif t == "qCom":
                        try:
                            qCom = float((child.text or "0").replace(",", "."))
                        except:
                            qCom = 0.0
                    elif t == "uCom": uCom = (child.text or "UN").strip().upper()
                itens.append({
                    "COD_NF": cProd,
                    "EAN_NF": cEAN if cEAN != "SEM GTIN" else "",
                    "PRODUTO_NF": xProd,
                    "QTD_NF": qCom,
                    "UND_NF": uCom,
                    "FORNECEDOR_NF": fornecedor_nf,
                    "NUMERO_NF": numero_nf
                })
    else:
        conteudo = arq_nf.read().decode("utf-8", errors="ignore")
        try:
            tabelas = pd.read_html(io.StringIO(conteudo), decimal=",", thousands=".")
        except:
            tabelas = []
        for tab in tabelas:
            if tab.shape[1] >= 3 and len(tab) >= 1:
                df_t = tab.copy()
                primeira_linha = " ".join(df_t.iloc[0].astype(str).tolist()).upper()
                if any(k in primeira_linha for k in ["DESCRI", "PRODUTO", "QUANT", "CÓD", "COD", "UNID", "VALOR"]):
                    df_t.columns = [str(c).strip().upper() for c in df_t.iloc[0]]
                    df_t = df_t[1:].reset_index(drop=True)
                else:
                    df_t.columns = [str(c).strip().upper() for c in df_t.columns]
                
                col_desc = next((c for c in df_t.columns if any(k in c for k in ["DESCRI", "PRODUTO", "DISCRIMINA", "XPROD", "MERCADORIA"])), None)
                col_qtd = next((c for c in df_t.columns if any(k in c for k in ["QUANT", "QTD", "QCOM"])), None)
                col_cod = next((c for c in df_t.columns if any(k in c for k in ["CÓD", "COD", "CPROD", "ITEM", "REF"])), None)
                col_ean = next((c for c in df_t.columns if any(k in c for k in ["EAN", "BARRA", "GTIN"])), None)
                col_und = next((c for c in df_t.columns if any(k in c for k in ["UN", "UND", "UCOM", "MEDIDA"])), None)
                col_forn = next((c for c in df_t.columns if "FORN" in c or "EMIT" in c), None)
                
                if col_desc and col_qtd:
                    for _, r in df_t.iterrows():
                        nome_p = str(r.get(col_desc, "")).strip().upper()
                        if not nome_p or nome_p in ["NAN", "NONE", "DESCRIÇÃO", "PRODUTO"]:
                            continue
                        raw_q = str(r.get(col_qtd, "0")).strip()
                        raw_q = re.sub(r"[^\d,.-]", "", raw_q)
                        if "," in raw_q and "." in raw_q:
                            raw_q = raw_q.replace(".", "").replace(",", ".")
                        elif "," in raw_q:
                            raw_q = raw_q.replace(",", ".")
                        try:
                            q_val = float(raw_q)
                        except:
                            q_val = 1.0
                        c_val = str(r.get(col_cod, "")).strip() if col_cod else ""
                        e_val = str(r.get(col_ean, "")).strip() if col_ean else ""
                        u_val = str(r.get(col_und, "UN")).strip().upper() if col_und else "UN"
                        f_val = str(r.get(col_forn, fornecedor_nf)).strip().upper() if col_forn else fornecedor_nf
                        itens.append({
                            "COD_NF": c_val if c_val.upper() != "NAN" else "",
                            "EAN_NF": e_val if e_val.upper() not in ["NAN", "SEM GTIN"] else "",
                            "PRODUTO_NF": nome_p,
                            "QTD_NF": q_val if q_val > 0 else 1.0,
                            "UND_NF": u_val if u_val != "NAN" else "UN",
                            "FORNECEDOR_NF": f_val if f_val != "NAN" else "FORNECEDOR NF",
                            "NUMERO_NF": numero_nf
                        })
                        
    map_ean = dict(zip(df_catalogo[df_catalogo["COD_BARRAS"] != ""]["COD_BARRAS"], df_catalogo["CODIGO"]))
    map_cod = dict(zip(df_catalogo["CODIGO"], df_catalogo["CODIGO"]))
    map_desc = dict(zip(df_catalogo["DESCRICAO"].str.upper().str.strip(), df_catalogo["CODIGO"]))
    
    for it in itens:
        cod_encontrado = None
        if it["EAN_NF"] and it["EAN_NF"] in map_ean:
            cod_encontrado = map_ean[it["EAN_NF"]]
        elif it["COD_NF"] and it["COD_NF"].zfill(6) in map_cod:
            cod_encontrado = it["COD_NF"].zfill(6)
        elif it["PRODUTO_NF"] in map_desc:
            cod_encontrado = map_desc[it["PRODUTO_NF"]]
        it["CODIGO_VINCULADO"] = cod_encontrado
        it["CADASTRADO"] = cod_encontrado is not None
        
    return itens

# Barra Lateral com Logomarca, Identificação Obrigatória e Fluxo do Processo
with st.sidebar:
    logo_bytes = carregar_logo()
    if logo_bytes:
        st.image(logo_bytes, use_container_width=True)
    else:
        st.title("📦 JJ EMBALAGENS")
    st.caption("Gestão de Estoque e Processos (Ultra Rápido)")
    st.divider()
    
    st.markdown("### 👤 Identificação Obrigatória")
    operador = st.text_input(
        "Nome Completo do Responsável:",
        value="",
        placeholder="Digite seu nome para liberar...",
        help="Obrigatório preencher o seu nome real para registrar qualquer entrada, baixa ou ajuste."
    )
    if not operador.strip():
        st.warning("⚠️ **Preencha seu nome acima.** Obrigatório para registrar Data, Hora e Responsável.")
    else:
        st.success(f"🟢 Operador Ativo: **{operador.strip().upper()}**")
        
    st.divider()
    st.markdown("### 🔄 Etapas do Processo")
    menu = st.radio(
        "Selecione o Módulo Operacional:",
        [
            "📤 1. Dar Baixa / Retirada (Múltipla)",
            "📥 2. Entrada (Manual ou HTML/XML NF)",
            "➕ 3. Cadastrar Produto / Zerar Estoque",
            "🔍 4. Relatório de Estoque e Exportação",
            "📊 5. Gráficos e Painel por Grupo",
            "📸 6. Auditoria de Movimentações e Avarias"
        ]
    )

df_produtos = carregar_produtos()
opcoes_busca = [""] + df_produtos["BUSCA_RAPIDA"].tolist()

# ==============================================================================
# TELA 1: DAR BAIXA / RETIRADA MÚLTIPLA + ATALHO DE ZERAR ESTOQUE COM SENHA (6994)
# ==============================================================================
if menu.startswith("📤"):
    st.markdown("""
        <div class="process-header">
            <h2>📤 Processo de Baixa / Retirada Múltipla de Estoque</h2>
            <p>Fluxo Padronizado: 1. Identificar Responsável ➔ 2. Empilhar Produtos no Romaneio ➔ 3. Informar Destino/Foto ➔ 4. Gravar Data, Hora e Baixa</p>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown('<span class="step-badge">ETAPA 1: SELECIONAR PRODUTOS PARA O ROMANEIO</span>', unsafe_allow_html=True)
    
    with st.form("form_add_saida", clear_on_submit=False):
        col_busca, col_qtd, col_btn = st.columns([3.2, 1, 1.2])
        with col_busca:
            item_selecionado = st.selectbox(
                "Pesquise por Código, Código de Barras (EAN) ou Descrição:",
                options=opcoes_busca,
                index=0
            )
        with col_qtd:
            qtd_retirada = st.number_input("Quantidade a retirar:", min_value=0.01, value=1.0, step=1.0)
        with col_btn:
            st.write("")
            st.write("")
            btn_add_saida = st.form_submit_button("➕ Adicionar ao Romaneio", use_container_width=True, type="primary")
            
        if btn_add_saida:
            if item_selecionado == "":
                st.warning("Selecione um produto antes de adicionar.")
            else:
                cod_sel = item_selecionado.split(" | ")[0]
                prod_row = df_produtos[df_produtos["CODIGO"] == cod_sel].iloc[0]
                st.session_state.carrinho_saida.append({
                    "CODIGO": prod_row["CODIGO"],
                    "COD_BARRAS": prod_row["COD_BARRAS"],
                    "DESCRICAO": prod_row["DESCRICAO"],
                    "GRUPO": prod_row["GRUPO"],
                    "QUANTIDADE": float(qtd_retirada),
                    "UNIDADE": prod_row["UND_VENDA"],
                    "SALDO_ATUAL": float(prod_row["SALDO_DEPOSITO"]),
                    "ESTOQUE_MINIMO": float(prod_row["ESTOQUE_MINIMO"])
                })
                st.success(f"Adicionado à lista: {prod_row['DESCRICAO']} ({qtd_retirada} {prod_row['UND_VENDA']})")

    # Atalho Rápido para Zerar Estoque do Produto com Senha Obrigatória (6994)
    with st.expander("🚨 Precisa ZERAR o estoque de um produto imediatamente? (Requer Senha de Autorização)"):
        with st.form("form_zerar_rapido"):
            cz1, cz2, cz3, cz4 = st.columns([2.5, 1.2, 1, 1.2])
            prod_zerar_rap = cz1.selectbox("Produto para Zerar Saldo:", options=opcoes_busca, key="zerar_rap_sel")
            motivo_zerar_rap = cz2.text_input("Motivo do Zeramento:", value="Ajuste de Inventário / Zeramento")
            senha_dig_rap = cz3.text_input("🔑 Senha Obrigatória:", type="password", placeholder="Senha...")
            cz4.write("")
            cz4.write("")
            btn_zerar_rap = cz4.form_submit_button("🚨 Zerar Estoque Agora", use_container_width=True)
            
            if btn_zerar_rap:
                if not operador.strip():
                    st.error("🚫 Informe o seu Nome Completo na barra lateral antes de zerar o estoque!")
                elif prod_zerar_rap == "":
                    st.warning("Selecione o produto que deseja zerar.")
                elif senha_dig_rap != SENHA_ZERAR:
                    st.error("🚫 SENHA INCORRETA! Operação bloqueada. A senha de autorização é obrigatória.")
                else:
                    cod_z = prod_zerar_rap.split(" | ")[0]
                    p_z = df_produtos[df_produtos["CODIGO"] == cod_z].iloc[0]
                    saldo_ant = float(p_z["SALDO_DEPOSITO"])
                    nome_op = operador.strip().upper()
                    data_str = date.today().strftime("%Y-%m-%d")
                    hora_str = datetime.now().strftime("%H:%M:%S")
                    data_hora_str = f"{date.today().strftime('%d/%m/%Y')} {hora_str}"
                    id_rom = "ZERO-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                    
                    cur = conn_global.cursor()
                    cur.execute("""
                        UPDATE produtos 
                        SET SALDO_DEPOSITO = 0.0,
                            ULTIMA_MOV_DATA = ?,
                            ULTIMA_MOV_HORA = ?,
                            ULTIMO_OPERADOR = ?
                        WHERE CODIGO = ?
                    """, (data_str, hora_str, nome_op, cod_z))
                    cur.execute("""
                        INSERT INTO movimentacoes 
                        (id_romaneio, data_registro, hora_registro, data_hora, tipo_operacao, motivo_destino, codigo_produto, cod_barras, descricao, grupo, quantidade, unidade, responsavel, nf_numero, observacao, caminho_foto)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        id_rom, data_str, hora_str, data_hora_str, "ZERAMENTO DE ESTOQUE",
                        "Estoque Zerado via Senha", cod_z, p_z["COD_BARRAS"], p_z["DESCRICAO"],
                        p_z["GRUPO"], saldo_ant, p_z["UND_VENDA"], nome_op, "",
                        f"Saldo anterior ({saldo_ant}) zerado com senha. Motivo: {motivo_zerar_rap}", ""
                    ))
                    conn_global.commit()
                    limpar_caches()
                    st.success(f"✅ Estoque do produto '{p_z['DESCRICAO']}' (Cód: {cod_z}) foi ZERADO com sucesso por {nome_op}!")
                    st.rerun()

    st.divider()
    
    st.markdown('<span class="step-badge">ETAPA 2: CONFERÊNCIA DO CARRINHO E REGISTRO DO RESPONSÁVEL</span>', unsafe_allow_html=True)
    st.subheader(f"🛒 Produtos Empilhados para Retirada ({len(st.session_state.carrinho_saida)} itens)")
    
    if len(st.session_state.carrinho_saida) == 0:
        st.info("Sua lista de retirada está vazia. Selecione um ou mais produtos acima e clique em '➕ Adicionar ao Romaneio'.")
    else:
        df_cesta = pd.DataFrame(st.session_state.carrinho_saida)
        st.dataframe(df_cesta, use_container_width=True, hide_index=True)
        
        col_limpar, _ = st.columns([1, 4])
        if col_limpar.button("🗑️ Esvaziar Lista"):
            st.session_state.carrinho_saida = []
            st.rerun()
            
        st.markdown("### 📋 Dados Obrigatórios da Baixa")
        c_resp, c_data, c_hora = st.columns([2, 1, 1])
        with c_resp:
            resp_confirmacao = st.text_input(
                "👤 Responsável pela Retirada (Obrigatório):",
                value=operador,
                placeholder="Digite o nome de quem está retirando os produtos..."
            )
        with c_data:
            data_baixa = st.date_input("📅 Data da Baixa:", value=date.today(), format="DD/MM/YYYY")
        with c_hora:
            hora_atual_str = datetime.now().strftime("%H:%M:%S")
            st.text_input("⏰ Hora do Registro:", value=hora_atual_str, disabled=True)
            
        col_dest, col_obs = st.columns(2)
        with col_dest:
            motivo = st.radio(
                "Destino / Motivo Operacional da Baixa:",
                [
                    "🏪 Reposição nas Prateleiras da Loja",
                    "🚚 Expedição / Venda Direta ao Cliente",
                    "⚠️ Baixa por Avaria / Produto Danificado",
                    "🔧 Consumo Interno / Ajuste Operacional"
                ]
            )
        with col_obs:
            observacao = st.text_area(
                "Observações do Processo (Obrigatório detalhar em caso de avaria):",
                placeholder="Ex: Reposição corredor central da loja / Produto amassado no transporte..."
            )
            
        foto_avaria = None
        if "Avaria" in motivo:
            st.error("📸 **TRAVA DE QUALIDADE:** Para baixa por **Avaria**, é OBRIGATÓRIO anexar a foto do produto avariado e descrever a ocorrência!")
            metodo_foto = st.radio(
                "Origem da Foto:",
                ["📁 Enviar da Galeria / Computador", "📷 Tirar Foto Agora (Câmera do Celular/PC)"],
                horizontal=True
            )
            if "Galeria" in metodo_foto:
                foto_avaria = st.file_uploader("Anexe a foto do produto avariado (JPG/PNG):", type=["jpg", "jpeg", "png"])
            else:
                foto_avaria = st.camera_input("Posicione o produto avariado na câmera:")
                
        if st.button("✅ Confirmar e Registrar Baixa no Estoque", type="primary", use_container_width=True):
            nome_final = resp_confirmacao.strip().upper()
            if not nome_final or nome_final == "OPERADOR ESTOQUE":
                st.error("🚫 **BLOQUEADO:** É obrigatório informar o **Nome Real da Pessoa** responsável pela baixa antes de registrar!")
            elif "Avaria" in motivo and (foto_avaria is None or not observacao.strip()):
                st.error("🚫 **BLOQUEADO:** Para baixa por avaria, anexe a fotografia obrigatória e preencha a observação!")
            else:
                id_rom = "ROM-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                data_str = data_baixa.strftime("%Y-%m-%d")
                data_br = data_baixa.strftime("%d/%m/%Y")
                hora_str = datetime.now().strftime("%H:%M:%S")
                data_hora_str = f"{data_br} {hora_str}"
                caminho_salvo = ""
                
                if foto_avaria is not None:
                    caminho_salvo = os.path.join(PASTA_FOTOS, f"{id_rom}.jpg")
                    with open(caminho_salvo, "wb") as f:
                        f.write(foto_avaria.getbuffer())
                        
                cur = conn_global.cursor()
                for item in st.session_state.carrinho_saida:
                    cur.execute("""
                        UPDATE produtos 
                        SET SALDO_DEPOSITO = SALDO_DEPOSITO - ?,
                            ULTIMA_MOV_DATA = ?,
                            ULTIMA_MOV_HORA = ?,
                            ULTIMO_OPERADOR = ?
                        WHERE CODIGO = ?
                    """, (item["QUANTIDADE"], data_str, hora_str, nome_final, item["CODIGO"]))
                    
                    if "Prateleiras da Loja" in motivo:
                        cur.execute(
                            "UPDATE produtos SET SALDO_LOJA = SALDO_LOJA + ? WHERE CODIGO = ?",
                            (item["QUANTIDADE"], item["CODIGO"])
                        )
                        
                    cur.execute("""
                        INSERT INTO movimentacoes 
                        (id_romaneio, data_registro, hora_registro, data_hora, tipo_operacao, motivo_destino, codigo_produto, cod_barras, descricao, grupo, quantidade, unidade, responsavel, nf_numero, observacao, caminho_foto)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        id_rom, data_str, hora_str, data_hora_str, "SAÍDA", motivo,
                        item["CODIGO"], item["COD_BARRAS"], item["DESCRICAO"], item["GRUPO"],
                        item["QUANTIDADE"], item["UNIDADE"], nome_final, "", observacao, caminho_salvo
                    ))
                conn_global.commit()
                limpar_caches()
                st.session_state.carrinho_saida = []
                st.success(f"✅ Baixa registrada com sucesso! Romaneio: {id_rom} | Responsável: {nome_final} | Data/Hora: {data_hora_str}")
                st.rerun()

# ==============================================================================
# TELA 2: ENTRADA DE PRODUTOS (MANUAL, CADASTRAR NOVO DIRETO OU NF COM AUTO-CADASTRO)
# ==============================================================================
elif menu.startswith("📥"):
    st.markdown("""
        <div class="process-header">
            <h2>📥 Processo de Recebimento e Entrada de Mercadorias</h2>
            <p>Fluxo Padronizado: Entrada Manual, Cadastro Direto de Produto Novo ou Importação de NF (HTML/XML) com reconhecimento automático de itens não cadastrados</p>
        </div>
    """, unsafe_allow_html=True)
    
    aba_manual, aba_nf = st.tabs(["📝 1. Entrada Manual (ou Cadastrar Novo Produto)", "📄 2. Importar HTML / XML da Nota Fiscal"])
    
    with aba_manual:
        tipo_acao_manual = st.radio(
            "Como deseja dar entrada no produto?",
            [
                "📦 Selecionar Produto Já Cadastrado no Catálogo",
                "➕ Cadastrar Novo Produto Manualmente (Código, Nome, Fornecedor e Quantidade)"
            ],
            horizontal=True
        )
        
        if tipo_acao_manual.startswith("📦"):
            with st.form("form_add_entrada", clear_on_submit=False):
                c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
                with c1:
                    prod_ent = st.selectbox("Selecione o Produto Recebido:", options=opcoes_busca, key="ent_sel")
                with c2:
                    qtd_ent = st.number_input("Qtd Recebida:", min_value=0.01, value=1.0, step=1.0, key="ent_qtd")
                with c3:
                    fator_mult = st.number_input("Unid. por Caixa/Fardo:", min_value=1.0, value=1.0, step=1.0)
                with c4:
                    st.write("")
                    st.write("")
                    btn_inc_ent = st.form_submit_button("➕ Incluir no Lote", use_container_width=True, type="primary")
                    
                if btn_inc_ent:
                    if prod_ent == "":
                        st.warning("Selecione um produto.")
                    else:
                        cod_e = prod_ent.split(" | ")[0]
                        p_row = df_produtos[df_produtos["CODIGO"] == cod_e].iloc[0]
                        qtd_final = float(qtd_ent * fator_mult)
                        st.session_state.carrinho_entrada.append({
                            "CODIGO": p_row["CODIGO"],
                            "COD_BARRAS": p_row["COD_BARRAS"],
                            "DESCRICAO": p_row["DESCRICAO"],
                            "FORNECEDOR": p_row["FORNECEDOR"],
                            "GRUPO": p_row["GRUPO"],
                            "QTD_TOTAL_ENTRADA": qtd_final,
                            "UNIDADE": p_row["UND_VENDA"]
                        })
                        st.success(f"Incluído no lote: {p_row['DESCRICAO']} (+{qtd_final} {p_row['UND_VENDA']})")
        else:
            st.markdown('<span class="step-badge">CADASTRO RÁPIDO MANUAL + ENTRADA DE ESTOQUE</span>', unsafe_allow_html=True)
            prox_cod_sugerido = str(len(df_produtos) + 39).zfill(6)
            with st.form("form_cad_manual_direto", clear_on_submit=True):
                cm1, cm2, cm3, cm4 = st.columns([1.2, 2.5, 2, 1.2])
                cod_novo_man = cm1.text_input("🔢 Código do Produto *:", value=prox_cod_sugerido, placeholder="Ex: 002876")
                nome_novo_man = cm2.text_input("🏷️ Nome do Produto *:", placeholder="Ex: SACOLA KRAFT DELIVERY M")
                forn_novo_man = cm3.text_input("🏭 Fornecedor *:", placeholder="Ex: EPV EMBALAGENS LTDA")
                qtd_novo_man = cm4.number_input("📦 Quantidade Inicial *:", min_value=0.0, value=1.0, step=1.0)
                
                cm5, cm6, cm7 = st.columns(3)
                und_novo_man = cm5.selectbox("Unidade:", ["UN", "CX", "PCT", "FD", "KGS", "MLH", "RL"])
                grupo_novo_man = cm6.text_input("Grupo / Família:", value="GERAL")
                min_novo_man = cm7.number_input("Estoque Mínimo de Segurança:", min_value=0.0, value=10.0, step=1.0)
                
                if st.form_submit_button("💾 Cadastrar Produto e Dar Entrada no Estoque", type="primary", use_container_width=True):
                    nome_op = operador.strip().upper()
                    if not nome_op:
                        st.error("🚫 Preencha o seu Nome Completo na barra lateral para registrar o cadastro!")
                    elif not cod_novo_man.strip() or not nome_novo_man.strip() or not forn_novo_man.strip():
                        st.error("🚫 Preencha obrigatoriamente o Código do Produto, Nome do Produto e Fornecedor!")
                    else:
                        cod_fmt = cod_novo_man.strip().zfill(6)
                        if cod_fmt in df_produtos["CODIGO"].values:
                            st.error(f"🚫 O código {cod_fmt} já está cadastrado no sistema! Escolha outro código.")
                        else:
                            data_str = date.today().strftime("%Y-%m-%d")
                            hora_str = datetime.now().strftime("%H:%M:%S")
                            data_hora_str = f"{date.today().strftime('%d/%m/%Y')} {hora_str}"
                            id_rom = "CAD-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                            
                            cur = conn_global.cursor()
                            cur.execute("""
                                INSERT INTO produtos 
                                (CODIGO, COD_BARRAS, DESCRICAO, UND_VENDA, UND_COMPRA, FATOR_CONVERSAO, GRUPO, FORNECEDOR, SALDO_DEPOSITO, SALDO_LOJA, ESTOQUE_MINIMO, PRECO_VENDA, SITUACAO, ULTIMA_MOV_DATA, ULTIMA_MOV_HORA, ULTIMO_OPERADOR)
                                VALUES (?, ?, ?, ?, ?, 1.0, ?, ?, ?, 0.0, ?, 0.0, 'Ativo', ?, ?, ?)
                            """, (
                                cod_fmt, cod_fmt, nome_novo_man.strip().upper(), und_novo_man, und_novo_man,
                                grupo_novo_man.strip().upper(), forn_novo_man.strip().upper(), float(qtd_novo_man),
                                float(min_novo_man), data_str, hora_str, nome_op
                            ))
                            cur.execute("""
                                INSERT INTO movimentacoes 
                                (id_romaneio, data_registro, hora_registro, data_hora, tipo_operacao, motivo_destino, codigo_produto, cod_barras, descricao, grupo, quantidade, unidade, responsavel, nf_numero, observacao, caminho_foto)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                id_rom, data_str, hora_str, data_hora_str, "CADASTRO + ENTRADA",
                                f"Fornecedor: {forn_novo_man.strip().upper()}", cod_fmt, cod_fmt,
                                nome_novo_man.strip().upper(), grupo_novo_man.strip().upper(),
                                float(qtd_novo_man), und_novo_man, nome_op, "",
                                f"Cadastro manual direto com saldo inicial ({qtd_novo_man})", ""
                            ))
                            conn_global.commit()
                            limpar_caches()
                            st.success(f"✅ Produto '{nome_novo_man.strip().upper()}' (Cód: {cod_fmt}) cadastrado com Fornecedor '{forn_novo_man.strip().upper()}' e saldo de {qtd_novo_man} {und_novo_man}!")
                            st.rerun()
                    
        if len(st.session_state.carrinho_entrada) > 0:
            st.divider()
            st.subheader("🛒 Lote de Entrada Manual")
            st.dataframe(pd.DataFrame(st.session_state.carrinho_entrada), use_container_width=True, hide_index=True)
            c_r1, c_r2, c_r3 = st.columns([2, 1, 2])
            resp_ent = c_r1.text_input("👤 Responsável pelo Recebimento (Obrigatório):", value=operador, key="resp_ent_man")
            data_ent = c_r2.date_input("📅 Data da Entrada:", value=date.today(), format="DD/MM/YYYY", key="dt_ent_man")
            nf_man = c_r3.text_input("Nº da Nota Fiscal / Pedido:")
            obs_man = st.text_input("Observação (Fornecedor / Conferência):")
            
            col_b1, col_b2 = st.columns([2, 1])
            if col_b1.button("✅ Confirmar Entrada no Estoque", type="primary", use_container_width=True):
                nome_ent = resp_ent.strip().upper()
                if not nome_ent:
                    st.error("🚫 Obrigatório informar o Nome do Responsável pelo recebimento!")
                else:
                    id_rom = "ENT-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                    data_str = data_ent.strftime("%Y-%m-%d")
                    data_br = data_ent.strftime("%d/%m/%Y")
                    hora_str = datetime.now().strftime("%H:%M:%S")
                    data_hora_str = f"{data_br} {hora_str}"
                    
                    cur = conn_global.cursor()
                    for item in st.session_state.carrinho_entrada:
                        cur.execute("""
                            UPDATE produtos 
                            SET SALDO_DEPOSITO = SALDO_DEPOSITO + ?,
                                ULTIMA_MOV_DATA = ?,
                                ULTIMA_MOV_HORA = ?,
                                ULTIMO_OPERADOR = ?
                            WHERE CODIGO = ?
                        """, (item["QTD_TOTAL_ENTRADA"], data_str, hora_str, nome_ent, item["CODIGO"]))
                        
                        cur.execute("""
                            INSERT INTO movimentacoes 
                            (id_romaneio, data_registro, hora_registro, data_hora, tipo_operacao, motivo_destino, codigo_produto, cod_barras, descricao, grupo, quantidade, unidade, responsavel, nf_numero, observacao, caminho_foto)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            id_rom, data_str, hora_str, data_hora_str, "ENTRADA", "Recebimento Manual",
                            item["CODIGO"], item["COD_BARRAS"], item["DESCRICAO"], item["GRUPO"],
                            item["QTD_TOTAL_ENTRADA"], item["UNIDADE"], nome_ent, nf_man, obs_man, ""
                        ))
                    conn_global.commit()
                    limpar_caches()
                    st.session_state.carrinho_entrada = []
                    st.success(f"🎉 Entrada registrada! Protocolo: {id_rom} | Responsável: {nome_ent}")
                    st.rerun()
            if col_b2.button("🗑️ Limpar Lote", use_container_width=True):
                st.session_state.carrinho_entrada = []
                st.rerun()

    with aba_nf:
        st.write("Suba o arquivo **HTML** ou **XML** da Nota Fiscal. O sistema reconhece automaticamente quais produtos já estão cadastrados e **solicita o cadastro dos produtos novos** antes de dar a entrada.")
        resp_nf = st.text_input("👤 Responsável pela Conferência/Importação da NF (Obrigatório):", value=operador, key="resp_nf_imp")
        arq_nf = st.file_uploader("Solte aqui o arquivo HTML ou XML da Nota Fiscal:", type=["html", "htm", "xml", "xls"])
        
        if arq_nf is not None:
            try:
                itens_nf = extrair_itens_nf(arq_nf, df_produtos)
                if len(itens_nf) == 0:
                    st.warning("Não foram encontrados itens de produtos estruturados neste arquivo.")
                else:
                    itens_cadastrados = [it for it in itens_nf if it["CADASTRADO"]]
                    itens_nao_cadastrados = [it for it in itens_nf if not it["CADASTRADO"]]
                    
                    m_nf1, m_nf2, m_nf3 = st.columns(3)
                    m_nf1.metric("Total de Itens na Nota Fiscal", len(itens_nf))
                    m_nf2.metric("🟢 Produtos Já Cadastrados", len(itens_cadastrados))
                    m_nf3.metric("🆕 Produtos NÃO Cadastrados", len(itens_nao_cadastrados))
                    
                    if len(itens_nao_cadastrados) > 0:
                        st.warning(f"⚠️ **ATENÇÃO:** Foram encontrados **{len(itens_nao_cadastrados)} produto(s) na Nota Fiscal que ainda NÃO estão cadastrados** no catálogo. Confira/preencha os campos abaixo (Código, Nome, Fornecedor e Quantidade) para cadastrá-los e dar entrada automaticamente, ou vincule a um item existente:")
                        
                        with st.form("form_cadastrar_novos_nf"):
                            dados_novos_nf = []
                            base_seq = len(df_produtos) + 40
                            for idx_n, it_n in enumerate(itens_nao_cadastrados):
                                st.markdown(f"**🆕 Item Não Cadastrado #{idx_n + 1} da Nota Fiscal:** `{it_n['PRODUTO_NF']}`")
                                cn1, cn2, cn3, cn4, cn5 = st.columns([1.1, 2.2, 1.8, 1, 1.8])
                                cod_sug = it_n["COD_NF"].zfill(6) if (it_n["COD_NF"] and it_n["COD_NF"].isdigit() and it_n["COD_NF"].zfill(6) not in df_produtos["CODIGO"].values) else str(base_seq + idx_n).zfill(6)
                                
                                c_cod = cn1.text_input("Código *:", value=cod_sug, key=f"nf_nc_cod_{idx_n}")
                                c_nome = cn2.text_input("Nome do Produto *:", value=it_n["PRODUTO_NF"], key=f"nf_nc_nom_{idx_n}")
                                c_forn = cn3.text_input("Fornecedor *:", value=it_n["FORNECEDOR_NF"], key=f"nf_nc_forn_{idx_n}")
                                c_qtd = cn4.number_input("Quantidade *:", value=float(it_n["QTD_NF"]), min_value=0.0, key=f"nf_nc_qtd_{idx_n}")
                                c_vinc_opc = cn5.selectbox("Ou vincular a existente:", options=["[CADASTRAR COMO NOVO]"] + opcoes_busca[1:], key=f"nf_nc_vinc_{idx_n}")
                                
                                dados_novos_nf.append({
                                    "CODIGO": c_cod.strip().zfill(6),
                                    "EAN": it_n["EAN_NF"] or c_cod.strip().zfill(6),
                                    "DESCRICAO": c_nome.strip().upper(),
                                    "FORNECEDOR": c_forn.strip().upper(),
                                    "QUANTIDADE": float(c_qtd),
                                    "UNIDADE": it_n["UND_NF"] or "UN",
                                    "VINCULO_EXISTENTE": c_vinc_opc,
                                    "NUMERO_NF": it_n["NUMERO_NF"]
                                })
                                st.divider()
                                
                            btn_cad_lote_nf = st.form_submit_button("💾 Cadastrar Produtos Novos da NF e Somar ao Estoque", type="primary", use_container_width=True)
                            if btn_cad_lote_nf:
                                nome_op_nf = resp_nf.strip().upper()
                                if not nome_op_nf:
                                    st.error("🚫 Informe o Nome do Responsável acima antes de cadastrar os itens da NF!")
                                else:
                                    data_str = date.today().strftime("%Y-%m-%d")
                                    hora_str = datetime.now().strftime("%H:%M:%S")
                                    data_hora_str = f"{date.today().strftime('%d/%m/%Y')} {hora_str}"
                                    id_rom = "NF-CAD-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                                    cur = conn_global.cursor()
                                    
                                    for d_item in dados_novos_nf:
                                        if d_item["VINCULO_EXISTENTE"] == "[CADASTRAR COMO NOVO]":
                                            cur.execute("""
                                                INSERT OR REPLACE INTO produtos 
                                                (CODIGO, COD_BARRAS, DESCRICAO, UND_VENDA, UND_COMPRA, FATOR_CONVERSAO, GRUPO, FORNECEDOR, SALDO_DEPOSITO, SALDO_LOJA, ESTOQUE_MINIMO, PRECO_VENDA, SITUACAO, ULTIMA_MOV_DATA, ULTIMA_MOV_HORA, ULTIMO_OPERADOR)
                                                VALUES (?, ?, ?, ?, ?, 1.0, 'GERAL', ?, ?, 0.0, 10.0, 0.0, 'Ativo', ?, ?, ?)
                                            """, (
                                                d_item["CODIGO"], d_item["EAN"], d_item["DESCRICAO"],
                                                d_item["UNIDADE"], d_item["UNIDADE"], d_item["FORNECEDOR"],
                                                d_item["QUANTIDADE"], data_str, hora_str, nome_op_nf
                                            ))
                                            cur.execute("""
                                                INSERT INTO movimentacoes 
                                                (id_romaneio, data_registro, hora_registro, data_hora, tipo_operacao, motivo_destino, codigo_produto, cod_barras, descricao, grupo, quantidade, unidade, responsavel, nf_numero, observacao, caminho_foto)
                                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                            """, (
                                                id_rom, data_str, hora_str, data_hora_str, "CADASTRO + ENTRADA NF",
                                                f"Fornecedor: {d_item['FORNECEDOR']}", d_item["CODIGO"], d_item["EAN"],
                                                d_item["DESCRICAO"], "GERAL", d_item["QUANTIDADE"], d_item["UNIDADE"],
                                                nome_op_nf, d_item["NUMERO_NF"], "Produto novo cadastrado via importação de NF", ""
                                            ))
                                        else:
                                            cod_ex = d_item["VINCULO_EXISTENTE"].split(" | ")[0]
                                            p_ex = df_produtos[df_produtos["CODIGO"] == cod_ex].iloc[0]
                                            cur.execute("""
                                                UPDATE produtos 
                                                SET SALDO_DEPOSITO = SALDO_DEPOSITO + ?,
                                                    ULTIMA_MOV_DATA = ?,
                                                    ULTIMA_MOV_HORA = ?,
                                                    ULTIMO_OPERADOR = ?
                                                WHERE CODIGO = ?
                                            """, (d_item["QUANTIDADE"], data_str, hora_str, nome_op_nf, cod_ex))
                                            cur.execute("""
                                                INSERT INTO movimentacoes 
                                                (id_romaneio, data_registro, hora_registro, data_hora, tipo_operacao, motivo_destino, codigo_produto, cod_barras, descricao, grupo, quantidade, unidade, responsavel, nf_numero, observacao, caminho_foto)
                                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                            """, (
                                                id_rom, data_str, hora_str, data_hora_str, "ENTRADA NF",
                                                "Importação NF (Vinculado)", cod_ex, p_ex["COD_BARRAS"],
                                                p_ex["DESCRICAO"], p_ex["GRUPO"], d_item["QUANTIDADE"], p_ex["UND_VENDA"],
                                                nome_op_nf, d_item["NUMERO_NF"], "Entrada via NF", ""
                                            ))
                                    conn_global.commit()
                                    limpar_caches()
                                    st.success(f"✅ {len(dados_novos_nf)} produto(s) cadastrado(s) e lançado(s) no estoque com sucesso!")
                                    st.rerun()
                                    
                    if len(itens_cadastrados) > 0:
                        st.subheader(f"🟢 Produtos Já Cadastrados Reconhecidos na NF ({len(itens_cadastrados)} itens)")
                        df_rec = pd.DataFrame(itens_cadastrados)[["CODIGO_VINCULADO", "EAN_NF", "PRODUTO_NF", "FORNECEDOR_NF", "QTD_NF", "UND_NF"]]
                        st.dataframe(df_rec, use_container_width=True, hide_index=True)
                        
                        if st.button("✅ Confirmar Entrada dos Produtos Já Cadastrados da NF", type="primary", use_container_width=True):
                            nome_op_nf = resp_nf.strip().upper()
                            if not nome_op_nf:
                                st.error("🚫 Informe o Nome do Responsável acima!")
                            else:
                                data_str = date.today().strftime("%Y-%m-%d")
                                hora_str = datetime.now().strftime("%H:%M:%S")
                                data_hora_str = f"{date.today().strftime('%d/%m/%Y')} {hora_str}"
                                id_rom = "NF-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                                cur = conn_global.cursor()
                                for it_c in itens_cadastrados:
                                    cod_c = it_c["CODIGO_VINCULADO"]
                                    p_c = df_produtos[df_produtos["CODIGO"] == cod_c].iloc[0]
                                    cur.execute("""
                                        UPDATE produtos 
                                        SET SALDO_DEPOSITO = SALDO_DEPOSITO + ?,
                                            ULTIMA_MOV_DATA = ?,
                                            ULTIMA_MOV_HORA = ?,
                                            ULTIMO_OPERADOR = ?
                                        WHERE CODIGO = ?
                                    """, (float(it_c["QTD_NF"]), data_str, hora_str, nome_op_nf, cod_c))
                                    cur.execute("""
                                        INSERT INTO movimentacoes 
                                        (id_romaneio, data_registro, hora_registro, data_hora, tipo_operacao, motivo_destino, codigo_produto, cod_barras, descricao, grupo, quantidade, unidade, responsavel, nf_numero, observacao, caminho_foto)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """, (
                                        id_rom, data_str, hora_str, data_hora_str, "ENTRADA NF",
                                        f"Fornecedor: {it_c['FORNECEDOR_NF']}", cod_c, p_c["COD_BARRAS"],
                                        p_c["DESCRICAO"], p_c["GRUPO"], float(it_c["QTD_NF"]), p_c["UND_VENDA"],
                                        nome_op_nf, it_c["NUMERO_NF"], "Entrada automática via NF", ""
                                    ))
                                conn_global.commit()
                                limpar_caches()
                                st.success(f"🎉 Entrada de {len(itens_cadastrados)} itens da Nota Fiscal registrada por {nome_op_nf}!")
                                st.rerun()
            except Exception as e:
                st.error(f"Erro ao processar o arquivo da Nota Fiscal: {e}")

# ==============================================================================
# TELA 3: CADASTRAR PRODUTO MANUALMENTE / ZERAR ESTOQUE COM SENHA (6994) / ESTOQUE MÍNIMO
# ==============================================================================
elif menu.startswith("➕"):
    st.markdown("""
        <div class="process-header">
            <h2>➕ Cadastro Manual de Produtos, Zeramento com Senha e Estoque Mínimo</h2>
            <p>Cadastre novos produtos (Código, Nome, Fornecedor e Quantidade), zere o saldo mediante senha (6994) ou parametrize o estoque mínimo</p>
        </div>
    """, unsafe_allow_html=True)
    
    aba_cad, aba_zerar, aba_min = st.tabs([
        "➕ 1. Cadastrar Novo Produto (Manual)",
        "🚨 2. Zerar Estoque de Produto (Requer Senha)",
        "🛡️ 3. Definir Estoque Mínimo (Individual ou Lote)"
    ])
    
    with aba_cad:
        st.markdown('<span class="step-badge">CADASTRO MANUAL DE NOVO PRODUTO NO CATÁLOGO</span>', unsafe_allow_html=True)
        st.write("Preencha os campos abaixo (**Código do Produto**, **Nome do Produto**, **Fornecedor** e **Quantidade**) para incluir um novo item no sistema.")
        prox_cod = str(len(df_produtos) + 39).zfill(6)
        
        with st.form("form_cadastro_principal", clear_on_submit=True):
            c1, c2 = st.columns([1, 2.5])
            novo_cod = c1.text_input("🔢 Código do Produto *:", value=prox_cod, placeholder="Ex: 002876")
            nova_desc = c2.text_input("🏷️ Nome / Descrição do Produto *:", placeholder="Ex: CAIXA PIZZA OITAVADA N35")
            
            c3, c4 = st.columns([2, 1.5])
            novo_forn = c3.text_input("🏭 Fornecedor *:", placeholder="Ex: F.L. EMBALAGENS LTDA")
            nova_qtd = c4.number_input("📦 Quantidade Inicial em Estoque *:", min_value=0.0, value=0.0, step=1.0)
            
            st.markdown("##### Informações Complementares (Opcionais)")
            c5, c6, c7, c8 = st.columns(4)
            novo_ean = c5.text_input("Código de Barras (EAN):", placeholder="Opcional")
            nova_und = c6.selectbox("Unidade de Controle:", ["UN", "CX", "PCT", "FD", "KGS", "MLH", "RL"])
            novo_grupo = c7.text_input("Grupo de Produtos:", value="GERAL")
            novo_est_min = c8.number_input("🛡️ Estoque Mínimo de Segurança:", min_value=0.0, value=10.0, step=1.0)
            
            if st.form_submit_button("💾 Cadastrar Produto no Sistema", type="primary", use_container_width=True):
                nome_op = operador.strip().upper()
                if not nome_op:
                    st.error("🚫 Informe o seu Nome Completo na barra lateral para registrar o cadastro!")
                elif not novo_cod.strip() or not nova_desc.strip() or not novo_forn.strip():
                    st.error("🚫 Os campos Código do Produto, Nome do Produto e Fornecedor são obrigatórios!")
                else:
                    cod_formatado = novo_cod.strip().zfill(6)
                    if cod_formatado in df_produtos["CODIGO"].values:
                        st.error(f"🚫 Já existe um produto com o código {cod_formatado}! Informe outro código.")
                    else:
                        ean_final = novo_ean.strip() if novo_ean.strip() else cod_formatado
                        data_str = date.today().strftime("%Y-%m-%d")
                        hora_str = datetime.now().strftime("%H:%M:%S")
                        data_hora_str = f"{date.today().strftime('%d/%m/%Y')} {hora_str}"
                        id_rom = "CAD-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                        
                        cur = conn_global.cursor()
                        cur.execute("""
                            INSERT INTO produtos 
                            (CODIGO, COD_BARRAS, DESCRICAO, UND_VENDA, UND_COMPRA, FATOR_CONVERSAO, GRUPO, FORNECEDOR, SALDO_DEPOSITO, SALDO_LOJA, ESTOQUE_MINIMO, PRECO_VENDA, SITUACAO, ULTIMA_MOV_DATA, ULTIMA_MOV_HORA, ULTIMO_OPERADOR)
                            VALUES (?, ?, ?, ?, ?, 1.0, ?, ?, ?, 0.0, ?, 0.0, 'Ativo', ?, ?, ?)
                        """, (
                            cod_formatado, ean_final, nova_desc.strip().upper(), nova_und, nova_und,
                            novo_grupo.strip().upper(), novo_forn.strip().upper(), float(nova_qtd),
                            float(novo_est_min), data_str, hora_str, nome_op
                        ))
                        cur.execute("""
                            INSERT INTO movimentacoes 
                            (id_romaneio, data_registro, hora_registro, data_hora, tipo_operacao, motivo_destino, codigo_produto, cod_barras, descricao, grupo, quantidade, unidade, responsavel, nf_numero, observacao, caminho_foto)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            id_rom, data_str, hora_str, data_hora_str, "CADASTRO MANUAL",
                            f"Fornecedor: {novo_forn.strip().upper()}", cod_formatado, ean_final,
                            nova_desc.strip().upper(), novo_grupo.strip().upper(), float(nova_qtd),
                            nova_und, nome_op, "", "Cadastro manual de novo produto", ""
                        ))
                        conn_global.commit()
                        limpar_caches()
                        st.success(f"✅ Produto '{nova_desc.strip().upper()}' (Cód: {cod_formatado} | Fornecedor: {novo_forn.strip().upper()}) cadastrado com quantidade {nova_qtd} {nova_und}!")
                        st.rerun()

    with aba_zerar:
        st.markdown('<span class="step-badge">OPERAÇÃO PROTEGIDA POR SENHA: ZERAR ESTOQUE DO PRODUTO SELECIONADO</span>', unsafe_allow_html=True)
        st.warning("🔒 **Atenção:** Esta operação zera imediatamente o saldo em depósito do produto selecionado e grava a auditoria (Data, Hora e Pessoa). É obrigatório inserir a **senha de autorização**.")
        
        prod_para_zerar = st.selectbox(
            "Selecione o Produto que deseja ZERAR o estoque:",
            options=opcoes_busca,
            key="sel_zerar_aba"
        )
        
        if prod_para_zerar != "":
            cod_z = prod_para_zerar.split(" | ")[0]
            linha_z = df_produtos[df_produtos["CODIGO"] == cod_z].iloc[0]
            
            z1, z2, z3 = st.columns(3)
            z1.metric("Código / Produto", f"{linha_z['CODIGO']} - {linha_z['DESCRICAO'][:28]}")
            z2.metric("Saldo Atual no Depósito", f"{linha_z['SALDO_DEPOSITO']} {linha_z['UND_VENDA']}")
            z3.metric("Fornecedor", str(linha_z["FORNECEDOR"])[:30])
            
            with st.form("form_zerar_estoque_aba"):
                obs_zerar = st.text_input("Motivo / Justificativa para Zerar o Estoque *:", placeholder="Ex: Contagem física zerada / Ajuste de balanço...")
                senha_zerar_input = st.text_input("🔑 Digite a Senha de Autorização Obrigatória *:", type="password", placeholder="Digite a senha de 4 dígitos...")
                
                if st.form_submit_button("🚨 Confirmar e ZERAR Estoque deste Produto", type="primary", use_container_width=True):
                    nome_op = operador.strip().upper()
                    if not nome_op:
                        st.error("🚫 Preencha o seu Nome Completo na barra lateral antes de zerar o estoque!")
                    elif senha_zerar_input != SENHA_ZERAR:
                        st.error("🚫 **SENHA INCORRETA!** Você não tem permissão para zerar o estoque sem a senha correta.")
                    elif not obs_zerar.strip():
                        st.error("🚫 Informe o motivo/justificativa do zeramento!")
                    else:
                        saldo_ant = float(linha_z["SALDO_DEPOSITO"])
                        data_str = date.today().strftime("%Y-%m-%d")
                        hora_str = datetime.now().strftime("%H:%M:%S")
                        data_hora_str = f"{date.today().strftime('%d/%m/%Y')} {hora_str}"
                        id_rom = "ZERO-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                        
                        cur = conn_global.cursor()
                        cur.execute("""
                            UPDATE produtos 
                            SET SALDO_DEPOSITO = 0.0,
                                ULTIMA_MOV_DATA = ?,
                                ULTIMA_MOV_HORA = ?,
                                ULTIMO_OPERADOR = ?
                            WHERE CODIGO = ?
                        """, (data_str, hora_str, nome_op, cod_z))
                        
                        cur.execute("""
                            INSERT INTO movimentacoes 
                            (id_romaneio, data_registro, hora_registro, data_hora, tipo_operacao, motivo_destino, codigo_produto, cod_barras, descricao, grupo, quantidade, unidade, responsavel, nf_numero, observacao, caminho_foto)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            id_rom, data_str, hora_str, data_hora_str, "ZERAMENTO DE ESTOQUE",
                            "Estoque Zerado com Senha", cod_z, linha_z["COD_BARRAS"], linha_z["DESCRICAO"],
                            linha_z["GRUPO"], saldo_ant, linha_z["UND_VENDA"], nome_op, "",
                            f"Saldo anterior ({saldo_ant}) zerado mediante senha. Justificativa: {obs_zerar}", ""
                        ))
                        conn_global.commit()
                        limpar_caches()
                        st.success(f"✅ O estoque do produto '{linha_z['DESCRICAO']}' foi ZERADO com sucesso por {nome_op} às {hora_str}!")
                        st.rerun()

    with aba_min:
        st.markdown('<span class="step-badge">AJUSTE DE ESTOQUE MÍNIMO EM LOTE OU INDIVIDUAL</span>', unsafe_allow_html=True)
        grupos_todos = sorted(df_produtos["GRUPO"].unique().tolist())
        with st.form("form_minimo_lote_grupo"):
            cl1, cl2, cl3 = st.columns([2.2, 1.3, 1])
            grupos_lote = cl1.multiselect("Selecione o(s) Grupo(s):", options=grupos_todos)
            modo_aplicacao = cl2.radio("Regra:", ["Aplicar em todos do grupo", "Apenas onde Mínimo <= 5"])
            valor_minimo_lote = cl3.number_input("🛡️ Novo Estoque Mínimo:", min_value=0.0, value=20.0, step=5.0)
            
            if st.form_submit_button("🚀 Aplicar Estoque Mínimo em Lote", type="primary", use_container_width=True):
                if len(grupos_lote) == 0:
                    st.warning("Selecione pelo menos um Grupo.")
                else:
                    cur = conn_global.cursor()
                    placeholders = ",".join(["?"] * len(grupos_lote))
                    if "Apenas" in modo_aplicacao:
                        query_lote = f"UPDATE produtos SET ESTOQUE_MINIMO = ? WHERE GRUPO IN ({placeholders}) AND ESTOQUE_MINIMO <= 5"
                    else:
                        query_lote = f"UPDATE produtos SET ESTOQUE_MINIMO = ? WHERE GRUPO IN ({placeholders})"
                    cur.execute(query_lote, [valor_minimo_lote] + grupos_lote)
                    qtd_afetada = cur.rowcount
                    conn_global.commit()
                    limpar_caches()
                    st.success(f"✅ Estoque Mínimo atualizado em {qtd_afetada} produtos!")
                    st.rerun()
                    
        st.divider()
        st.subheader("🛡️ Ajustar Estoque Mínimo ou Fornecedor Individualmente")
        prod_ajuste = st.selectbox("Selecione o Produto:", options=opcoes_busca, key="sel_minimo_ind")
        if prod_ajuste != "":
            cod_aj = prod_ajuste.split(" | ")[0]
            linha_p = df_produtos[df_produtos["CODIGO"] == cod_aj].iloc[0]
            with st.form("form_atualizar_minimo"):
                cm1, cm2, cm3 = st.columns(3)
                novo_minimo = cm1.number_input("🛡️ Estoque Mínimo de Segurança:", min_value=0.0, value=float(linha_p["ESTOQUE_MINIMO"]), step=1.0)
                novo_forn_aj = cm2.text_input("🏭 Fornecedor:", value=str(linha_p["FORNECEDOR"]))
                novo_grupo_aj = cm3.text_input("📦 Grupo:", value=str(linha_p["GRUPO"]))
                if st.form_submit_button("💾 Salvar Parâmetros do Produto", type="primary"):
                    cur = conn_global.cursor()
                    cur.execute("""
                        UPDATE produtos 
                        SET ESTOQUE_MINIMO = ?, FORNECEDOR = ?, GRUPO = ?
                        WHERE CODIGO = ?
                    """, (novo_minimo, novo_forn_aj.strip().upper(), novo_grupo_aj.strip().upper(), cod_aj))
                    conn_global.commit()
                    limpar_caches()
                    st.success("✅ Dados do produto atualizados com sucesso!")
                    st.rerun()

# ==============================================================================
# TELA 4: RELATÓRIO DE ESTOQUE, FILTRO POR DATA E PESSOA E DOWNLOAD SOB DEMANDA
# ==============================================================================
elif menu.startswith("🔍"):
    st.markdown("""
        <div class="process-header">
            <h2>🔍 Relatório Geral de Estoque, Rastreabilidade e Exportação</h2>
            <p>Consulte a posição atual de estoque com Data, Hora e Pessoa da última movimentação, filtre por período/operador e baixe em Excel ou CSV</p>
        </div>
    """, unsafe_allow_html=True)
    
    df_mov_all = carregar_movimentacoes()
    
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total de SKUs no Catálogo", f"{len(df_produtos):,}".replace(",", "."))
    k2.metric("🟢 Com Saldo Positivo (>0)", f"{int((df_produtos['SALDO_DEPOSITO'] > 0).sum()):,}".replace(",", "."))
    k3.metric("🟡 Abaixo do Estoque Mínimo", f"{int(((df_produtos['SALDO_DEPOSITO'] > 0) & (df_produtos['SALDO_DEPOSITO'] < df_produtos['ESTOQUE_MINIMO'])).sum()):,}".replace(",", "."))
    k4.metric("🔴 Em Ruptura / Zerados", f"{int((df_produtos['SALDO_DEPOSITO'] <= 0).sum()):,}".replace(",", "."))
    
    st.markdown("### 🎛️ Filtros de Pesquisa (Por Produto, Grupo, Data e Pessoa)")
    f1, f2, f3, f4 = st.columns([2, 1.3, 1.3, 1.4])
    
    termo = f1.text_input("🔎 Buscar por Nome, Código, Fornecedor ou EAN:")
    grupo_sel = f2.selectbox("📦 Filtrar por Grupo:", ["Todos"] + sorted(df_produtos["GRUPO"].unique().tolist()))
    
    lista_pessoas = sorted([p for p in pd.concat([df_produtos["ULTIMO_OPERADOR"], df_mov_all["responsavel"]]).dropna().unique().tolist() if str(p).strip() != ""])
    pessoa_sel = f3.selectbox("👤 Filtrar por Pessoa / Operador:", ["Todos"] + lista_pessoas)
    
    status_filtro = f4.selectbox("🚦 Semáforo de Estoque Mínimo:", [
        "Todos",
        "🟢 Confortável (>= Mínimo)",
        "🟡 Abaixo do Estoque Mínimo (Repor)",
        "🔴 Em Ruptura / Zerado (<= 0)"
    ])
    
    fd1, fd2, _ = st.columns([1.2, 1.5, 2.3])
    usar_filtro_data = fd1.checkbox("📅 Filtrar por Data de Movimentação")
    intervalo_datas = None
    if usar_filtro_data:
        intervalo_datas = fd2.date_input(
            "Selecione o Período (Início e Fim):",
            value=(date.today(), date.today()),
            format="DD/MM/YYYY"
        )
        
    df_view = df_produtos
    if termo:
        t_up = termo.upper()
        df_view = df_view[
            df_view["DESCRICAO"].str.upper().str.contains(t_up, na=False) |
            df_view["CODIGO"].str.contains(t_up, na=False) |
            df_view["COD_BARRAS"].str.contains(t_up, na=False) |
            df_view["FORNECEDOR"].str.upper().str.contains(t_up, na=False)
        ]
    if grupo_sel != "Todos":
        df_view = df_view[df_view["GRUPO"] == grupo_sel]
    if pessoa_sel != "Todos":
        cods_pessoa = df_mov_all[df_mov_all["responsavel"] == pessoa_sel]["codigo_produto"].unique().tolist()
        df_view = df_view[(df_view["ULTIMO_OPERADOR"] == pessoa_sel) | (df_view["CODIGO"].isin(cods_pessoa))]
    if status_filtro.startswith("🟢"):
        df_view = df_view[df_view["SALDO_DEPOSITO"] >= df_view["ESTOQUE_MINIMO"]]
    elif status_filtro.startswith("🟡"):
        df_view = df_view[(df_view["SALDO_DEPOSITO"] < df_view["ESTOQUE_MINIMO"]) & (df_view["SALDO_DEPOSITO"] > 0)]
    elif status_filtro.startswith("🔴"):
        df_view = df_view[df_view["SALDO_DEPOSITO"] <= 0]
        
    if usar_filtro_data and isinstance(intervalo_datas, tuple) and len(intervalo_datas) == 2:
        dt_ini = intervalo_datas[0].strftime("%Y-%m-%d")
        dt_fim = intervalo_datas[1].strftime("%Y-%m-%d")
        mov_periodo = df_mov_all[(df_mov_all["data_registro"] >= dt_ini) & (df_mov_all["data_registro"] <= dt_fim)]
        if pessoa_sel != "Todos":
            mov_periodo = mov_periodo[mov_periodo["responsavel"] == pessoa_sel]
        cods_periodo = mov_periodo["codigo_produto"].unique().tolist()
        df_view = df_view[
            ((df_view["ULTIMA_MOV_DATA"] >= dt_ini) & (df_view["ULTIMA_MOV_DATA"] <= dt_fim)) |
            (df_view["CODIGO"].isin(cods_periodo))
        ]
        
    colunas_relatorio = [
        "CODIGO", "COD_BARRAS", "DESCRICAO", "FORNECEDOR", "GRUPO", "UND_VENDA",
        "SALDO_DEPOSITO", "SALDO_LOJA", "ESTOQUE_MINIMO", "STATUS_ESTOQUE",
        "ULTIMA_MOV_DATA", "ULTIMA_MOV_HORA", "ULTIMO_OPERADOR"
    ]
    
    st.markdown(f"**Exibindo {len(df_view)} produtos filtrados:**")
    st.dataframe(df_view[colunas_relatorio], use_container_width=True, hide_index=True, height=420)
    
    st.markdown("### 📥 Baixar Base de Estoque / Relatório Filtrado")
    dl1, dl2, dl3 = st.columns(3)
    
    csv_estoque = df_view[colunas_relatorio].to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    dl1.download_button(
        label="⚡ Baixar Base de Estoque (.CSV - Instantâneo)",
        data=csv_estoque,
        file_name=f"Base_Estoque_JJ_{date.today().strftime('%d_%m_%Y')}.csv",
        mime="text/csv",
        use_container_width=True,
        type="primary"
    )
    
    if dl2.button("📊 Preparar Arquivo Excel (.XLSX)", use_container_width=True):
        excel_estoque = gerar_excel_bytes(df_view[colunas_relatorio], "Posicao_Estoque")
        dl2.download_button(
            label="⬇️ Clique para Salvar o Excel (.XLSX)",
            data=excel_estoque,
            file_name=f"Relatorio_Estoque_JJ_{date.today().strftime('%d_%m_%Y')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    
    if dl3.button("📋 Preparar Histórico Data/Pessoa (.XLSX)", use_container_width=True):
        df_mov_dl = df_mov_all.copy()
        if pessoa_sel != "Todos":
            df_mov_dl = df_mov_dl[df_mov_dl["responsavel"] == pessoa_sel]
        if usar_filtro_data and isinstance(intervalo_datas, tuple) and len(intervalo_datas) == 2:
            dt_ini = intervalo_datas[0].strftime("%Y-%m-%d")
            dt_fim = intervalo_datas[1].strftime("%Y-%m-%d")
            df_mov_dl = df_mov_dl[(df_mov_dl["data_registro"] >= dt_ini) & (df_mov_dl["data_registro"] <= dt_fim)]
        excel_mov = gerar_excel_bytes(df_mov_dl, "Movimentacoes_Data_Pessoa")
        dl3.download_button(
            label="⬇️ Clique para Salvar Histórico (.XLSX)",
            data=excel_mov,
            file_name=f"Movimentacoes_Data_Pessoa_JJ_{date.today().strftime('%d_%m_%Y')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

# ==============================================================================
# TELA 5: ABA COM GRÁFICOS PARA FILTRAR QUANTIDADE DE ESTOQUE POR GRUPO
# ==============================================================================
elif menu.startswith("📊"):
    import plotly.express as px
    
    st.markdown("""
        <div class="process-header">
            <h2>📊 Painel Analítico: Quantidade de Estoque por Grupo de Produtos</h2>
            <p>Visualização gerencial de volume em estoque, cumprimento do estoque mínimo de segurança e distribuição por família</p>
        </div>
    """, unsafe_allow_html=True)
    
    grupos_disponiveis = sorted(df_produtos["GRUPO"].unique().tolist())
    grupos_escolhidos = st.multiselect(
        "🔎 Filtrar Grupos de Produtos para Análise (deixe vazio para ver os Top 15 Grupos):",
        options=grupos_disponiveis,
        default=[]
    )
    
    df_graf = df_produtos if len(grupos_escolhidos) == 0 else df_produtos[df_produtos["GRUPO"].isin(grupos_escolhidos)]
        
    resumo_grupo = (
        df_graf.groupby("GRUPO", as_index=False)
        .agg(
            QTD_SKUS=("CODIGO", "count"),
            SALDO_DEPOSITO_TOTAL=("SALDO_DEPOSITO", "sum"),
            SALDO_LOJA_TOTAL=("SALDO_LOJA", "sum"),
            ESTOQUE_MINIMO_TOTAL=("ESTOQUE_MINIMO", "sum")
        )
        .sort_values(by="SALDO_DEPOSITO_TOTAL", ascending=False)
    )
    
    resumo_grupo_top = resumo_grupo.head(15) if len(grupos_escolhidos) == 0 else resumo_grupo
        
    g1, g2 = st.columns([1.4, 1])
    with g1:
        fig_bar = px.bar(
            resumo_grupo_top,
            x="SALDO_DEPOSITO_TOTAL",
            y="GRUPO",
            orientation="h",
            text_auto=".2s",
            title="📦 Quantidade Total em Estoque por Grupo de Produtos",
            labels={"SALDO_DEPOSITO_TOTAL": "Quantidade Total no Depósito", "GRUPO": "Grupo de Produtos"},
            color="SALDO_DEPOSITO_TOTAL",
            color_continuous_scale=["#FADBD8", "#F5B041", "#9E1B1B"]
        )
        fig_bar.update_layout(yaxis={'categoryorder': 'total ascending'}, height=460)
        st.plotly_chart(fig_bar, use_container_width=True)
        
    with g2:
        resumo_status = df_graf["STATUS_ESTOQUE"].value_counts().reset_index()
        resumo_status.columns = ["Status de Segurança", "Quantidade de Produtos"]
        fig_pie = px.pie(
            resumo_status,
            names="Status de Segurança",
            values="Quantidade de Produtos",
            hole=0.45,
            title="🚦 Saúde do Estoque vs. Estoque Mínimo",
            color="Status de Segurança",
            color_discrete_map={
                "🟢 ESTOQUE CONFORTÁVEL": "#27AE60",
                "🟠 ALERTA DE SEGURANÇA": "#F39C12",
                "🟡 ABAIXO DO MÍNIMO (REPOR)": "#F1C40F",
                "🔴 RUPTURA / ZERADO": "#C0392B"
            }
        )
        fig_pie.update_layout(height=460)
        st.plotly_chart(fig_pie, use_container_width=True)
        
    st.subheader("📋 Comparativo Produto a Produto: Saldo Atual vs. Estoque Mínimo de Segurança")
    grupo_detalhe = st.selectbox("Selecione um Grupo específico para inspecionar os produtos:", options=["Todos os Selecionados"] + grupos_disponiveis)
    df_det = df_graf if grupo_detalhe == "Todos os Selecionados" else df_produtos[df_produtos["GRUPO"] == grupo_detalhe]
    
    fig_comp = px.bar(
        df_det.sort_values(by="SALDO_DEPOSITO", ascending=False).head(25),
        x="DESCRICAO",
        y=["SALDO_DEPOSITO", "ESTOQUE_MINIMO"],
        barmode="group",
        title=f"Top 25 Produtos ({grupo_detalhe}): Saldo Atual no Depósito vs. Estoque Mínimo de Segurança",
        labels={"value": "Quantidade", "DESCRICAO": "Produto", "variable": "Indicador"},
        color_discrete_map={"SALDO_DEPOSITO": "#9E1B1B", "ESTOQUE_MINIMO": "#F5B041"}
    )
    fig_comp.update_layout(height=420, xaxis_tickangle=-30)
    st.plotly_chart(fig_comp, use_container_width=True)

# ==============================================================================
# TELA 6: AUDITORIA DE MOVIMENTAÇÕES E AVARIAS
# ==============================================================================
elif menu.startswith("📸"):
    st.markdown("""
        <div class="process-header">
            <h2>📸 Histórico de Movimentações e Auditoria de Avarias</h2>
            <p>Rastreabilidade total de quem retirou, cadastrou, deu entrada ou zerou estoque, com filtro por Data, Hora, Pessoa e Fotos</p>
        </div>
    """, unsafe_allow_html=True)
    
    df_mov = carregar_movimentacoes()
    
    if len(df_mov) == 0:
        st.info("Nenhuma movimentação registrada até o momento.")
    else:
        c_m1, c_m2, c_m3 = st.columns(3)
        filtro_motivo = c_m1.selectbox("Filtrar por Tipo de Operação:", [
            "Todas as Movimentações",
            "Apenas Baixas (Saídas)",
            "Apenas Baixas por Avaria (com Foto)",
            "Apenas Reposição de Loja",
            "Apenas Entradas / Cadastros",
            "Apenas Zeramentos de Estoque (Senha)"
        ])
        pessoas_hist = ["Todos"] + sorted([p for p in df_mov["responsavel"].dropna().unique().tolist() if str(p).strip() != ""])
        filtro_pessoa_hist = c_m2.selectbox("👤 Filtrar por Pessoa / Responsável:", pessoas_hist)
        
        usar_dt_hist = c_m3.checkbox("📅 Filtrar Período de Datas", value=False)
        df_m_view = df_mov
        
        if usar_dt_hist:
            dt_range = st.date_input("Período da Movimentação:", value=(date.today(), date.today()), format="DD/MM/YYYY", key="dt_hist")
            if isinstance(dt_range, tuple) and len(dt_range) == 2:
                d1, d2 = dt_range[0].strftime("%Y-%m-%d"), dt_range[1].strftime("%Y-%m-%d")
                df_m_view = df_m_view[(df_m_view["data_registro"] >= d1) & (df_m_view["data_registro"] <= d2)]
                
        if "Saídas" in filtro_motivo:
            df_m_view = df_m_view[df_m_view["tipo_operacao"] == "SAÍDA"]
        elif "Avaria" in filtro_motivo:
            df_m_view = df_m_view[df_m_view["motivo_destino"].str.contains("Avaria", na=False)]
        elif "Loja" in filtro_motivo:
            df_m_view = df_m_view[df_m_view["motivo_destino"].str.contains("Loja", na=False)]
        elif "Entradas" in filtro_motivo:
            df_m_view = df_m_view[df_m_view["tipo_operacao"].str.contains("ENTRADA|CADASTRO", na=False)]
        elif "Zeramentos" in filtro_motivo:
            df_m_view = df_m_view[df_m_view["tipo_operacao"].str.contains("ZERAMENTO", na=False)]
            
        if filtro_pessoa_hist != "Todos":
            df_m_view = df_m_view[df_m_view["responsavel"] == filtro_pessoa_hist]
            
        st.dataframe(df_m_view, use_container_width=True, hide_index=True)
        
        b_exp1, b_exp2 = st.columns(2)
        b_exp1.download_button(
            "⚡ Baixar Movimentações Filtradas (.CSV - Instantâneo)",
            data=df_m_view.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
            file_name=f"Auditoria_Movimentacoes_JJ_{date.today().strftime('%d_%m_%Y')}.csv",
            mime="text/csv",
            use_container_width=True,
            type="primary"
        )
        if b_exp2.button("📊 Preparar Relatório em Excel (.XLSX)", use_container_width=True):
            b_exp2.download_button(
                "⬇️ Clique para Salvar Excel (.XLSX)",
                data=gerar_excel_bytes(df_m_view, "Auditoria_Movimentacoes"),
                file_name=f"Auditoria_Movimentacoes_JJ_{date.today().strftime('%d_%m_%Y')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        
        df_fotos = df_m_view[df_m_view["caminho_foto"] != ""]
        if len(df_fotos) > 0:
            st.subheader("📸 Evidências Fotográficas de Avarias")
            for _, r_foto in df_fotos.iterrows():
                with st.expander(f"📸 {r_foto['data_hora']} | {r_foto['descricao']} (Qtd: {r_foto['quantidade']}) — Responsável: {r_foto['responsavel']}"):
                    st.write(f"**Observação registrada:** {r_foto['observacao']}")
                    if os.path.exists(r_foto["caminho_foto"]):
                        st.image(r_foto["caminho_foto"], width=420)
