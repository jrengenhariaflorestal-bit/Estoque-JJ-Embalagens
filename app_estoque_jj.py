import streamlit as st
import pandas as pd
import sqlite3
import os
import io
from datetime import datetime, date
import xml.etree.ElementTree as ET
import plotly.express as px

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
os.makedirs(PASTA_FOTOS, exist_ok=True)

# Estilo Visual Orientado a Processos / Gestão à Vista (Kanban / Lean)
st.markdown("""
    <style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }
    .process-header {
        background: linear-gradient(90deg, #9E1B1B 0%, #781212 100%);
        color: white;
        padding: 16px 22px;
        border-radius: 10px;
        margin-bottom: 18px;
        border-left: 8px solid #F5B041;
        box-shadow: 0 3px 8px rgba(0,0,0,0.12);
    }
    .process-header h2 {
        margin: 0;
        font-size: 1.45rem;
        color: #FFFFFF !important;
        font-weight: 700;
    }
    .process-header p {
        margin: 4px 0 0 0;
        font-size: 0.92rem;
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
        transition: all 0.2s ease;
    }
    div[data-testid="stMetric"] {
        background-color: #FFFFFF;
        border: 1px solid #E5E8E8;
        border-left: 5px solid #9E1B1B;
        padding: 12px 16px;
        border-radius: 8px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    }
    div[data-testid="stMetricValue"] {
        color: #9E1B1B;
        font-weight: 700;
    }
    </style>
""", unsafe_allow_html=True)

def conectar_db():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

# OTIMIZAÇÃO 1: Inicializa o banco e cria índices apenas UMA vez por sessão do servidor
@st.cache_resource
def inicializar_banco():
    conn = conectar_db()
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
            df_init = pd.read_csv(CSV_INICIAL, dtype={'CODIGO': str, 'COD_BARRAS': str})
            df_init['CODIGO'] = df_init['CODIGO'].str.zfill(6)
            for col_extra, val_padrao in [
                ('ULTIMA_MOV_DATA', ''),
                ('ULTIMA_MOV_HORA', ''),
                ('ULTIMO_OPERADOR', '')
            ]:
                if col_extra not in df_init.columns:
                    df_init[col_extra] = val_padrao
            df_init.to_sql("produtos", conn, if_exists="replace", index=False)
    else:
        cursor.execute("PRAGMA table_info(produtos)")
        colunas_prod = [col[1] for col in cursor.fetchall()]
        for col_extra in ['ULTIMA_MOV_DATA', 'ULTIMA_MOV_HORA', 'ULTIMO_OPERADOR']:
            if col_extra not in colunas_prod:
                cursor.execute(f"ALTER TABLE produtos ADD COLUMN {col_extra} TEXT DEFAULT ''")
    
    # Criação de Índices SQL para deixar buscas e atualizações instantâneas
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prod_codigo ON produtos(CODIGO)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prod_grupo ON produtos(GRUPO)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_mov_data ON movimentacoes(data_registro)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_mov_resp ON movimentacoes(responsavel)")
    
    conn.commit()
    conn.close()
    return True

inicializar_banco()

if "carrinho_saida" not in st.session_state:
    st.session_state.carrinho_saida = []
if "carrinho_entrada" not in st.session_state:
    st.session_state.carrinho_entrada = []

# OTIMIZAÇÃO 2: Cache em memória RAM + Cálculo Vetorizado (100x mais rápido que .apply)
@st.cache_data(ttl=300, show_spinner=False)
def carregar_produtos():
    conn = conectar_db()
    df = pd.read_sql("SELECT * FROM produtos", conn)
    conn.close()
    
    for c in ["SALDO_DEPOSITO", "SALDO_LOJA", "ESTOQUE_MINIMO", "PRECO_VENDA"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
            
    for c_txt in ["ULTIMA_MOV_DATA", "ULTIMA_MOV_HORA", "ULTIMO_OPERADOR", "COD_BARRAS", "DESCRICAO", "GRUPO", "UND_VENDA"]:
        if c_txt not in df.columns:
            df[c_txt] = ""
        else:
            df[c_txt] = df[c_txt].fillna("").astype(str)
            
    # Semáforo Vetorizado (Instantâneo para 2.837 linhas)
    df["STATUS_ESTOQUE"] = "🟢 ESTOQUE CONFORTÁVEL"
    mask_alerta = (df["SALDO_DEPOSITO"] <= df["ESTOQUE_MINIMO"] * 1.25) & (df["SALDO_DEPOSITO"] >= df["ESTOQUE_MINIMO"])
    mask_abaixo = (df["SALDO_DEPOSITO"] < df["ESTOQUE_MINIMO"]) & (df["SALDO_DEPOSITO"] > 0)
    mask_ruptura = df["SALDO_DEPOSITO"] <= 0
    
    df.loc[mask_alerta, "STATUS_ESTOQUE"] = "🟠 ALERTA DE SEGURANÇA"
    df.loc[mask_abaixo, "STATUS_ESTOQUE"] = "🟡 ABAIXO DO MÍNIMO (REPOR)"
    df.loc[mask_ruptura, "STATUS_ESTOQUE"] = "🔴 RUPTURA / ZERADO"
    
    # Coluna de busca pré-calculada em cache
    df["BUSCA_RAPIDA"] = (
        df["CODIGO"] + " | " +
        df["DESCRICAO"] + " | EAN: " +
        df["COD_BARRAS"] + " [Saldo: " +
        df["SALDO_DEPOSITO"].round(1).astype(str) + " " +
        df["UND_VENDA"] + " | Mín: " +
        df["ESTOQUE_MINIMO"].round(1).astype(str) + "]"
    )
    return df

@st.cache_data(ttl=120, show_spinner=False)
def carregar_movimentacoes():
    conn = conectar_db()
    df_m = pd.read_sql("SELECT * FROM movimentacoes ORDER BY id DESC", conn)
    conn.close()
    return df_m

def limpar_caches():
    carregar_produtos.clear()
    carregar_movimentacoes.clear()

# OTIMIZAÇÃO 3: Só gera o arquivo Excel quando o usuário realmente clicar para baixar
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

# Barra Lateral com Logomarca, Identificação Obrigatória e Fluxo do Processo
with st.sidebar:
    logo_bytes = carregar_logo()
    if logo_bytes:
        st.image(logo_bytes, use_container_width=True)
    else:
        st.title("📦 JJ EMBALAGENS")
    st.caption("Sistema de Gestão de Estoque e Processos (Alta Performance)")
    st.divider()
    
    st.markdown("### 👤 Identificação Obrigatória")
    operador = st.text_input(
        "Nome Completo do Responsável:",
        value="",
        placeholder="Digite seu nome para liberar...",
        help="Obrigatório preencher o seu nome real para registrar qualquer entrada ou baixa no sistema."
    )
    if not operador.strip():
        st.warning("⚠️ **Preencha seu nome acima.** O sistema exige identificação para registrar Data, Hora e Responsável.")
    else:
        st.success(f"🟢 Operador Ativo: **{operador.strip().upper()}**")
        
    st.divider()
    st.markdown("### 🔄 Etapas do Processo")
    menu = st.radio(
        "Selecione o Módulo Operacional:",
        [
            "📤 1. Dar Baixa / Retirada (Múltipla)",
            "📥 2. Entrada (Manual ou HTML/XML NF)",
            "🔍 3. Relatório de Estoque e Exportação",
            "📊 4. Gráficos e Painel por Grupo",
            "📸 5. Auditoria de Movimentações e Avarias",
            "⚙️ 6. Cadastrar / Definir Estoque Mínimo"
        ]
    )

df_produtos = carregar_produtos()
opcoes_busca = [""] + df_produtos["BUSCA_RAPIDA"].tolist()

# ==============================================================================
# TELA 1: DAR BAIXA / RETIRADA MÚLTIPLA (COM FORMULÁRIO PARA EVITAR RECARREGAMENTO)
# ==============================================================================
if menu.startswith("📤"):
    st.markdown("""
        <div class="process-header">
            <h2>📤 Processo de Baixa / Retirada Múltipla de Estoque</h2>
            <p>Fluxo Padronizado: 1. Identificar Responsável ➔ 2. Empilhar Produtos no Romaneio ➔ 3. Informar Destino/Foto ➔ 4. Gravar Data, Hora e Baixa</p>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown('<span class="step-badge">ETAPA 1: SELECIONAR PRODUTOS PARA O ROMANEIO</span>', unsafe_allow_html=True)
    
    # Uso de st.form evita que o app recarregue a cada dígito na quantidade
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
                        
                conn = conectar_db()
                cur = conn.cursor()
                
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
                conn.commit()
                conn.close()
                limpar_caches()
                st.session_state.carrinho_saida = []
                st.success(f"✅ Baixa registrada com sucesso! Romaneio: {id_rom} | Responsável: {nome_final} | Data/Hora: {data_hora_str}")
                st.rerun()

# ==============================================================================
# TELA 2: ENTRADA DE PRODUTOS (MANUAL EM LOTE OU HTML/XML DA NOTA FISCAL)
# ==============================================================================
elif menu.startswith("📥"):
    st.markdown("""
        <div class="process-header">
            <h2>📥 Processo de Recebimento e Entrada de Mercadorias</h2>
            <p>Fluxo Padronizado: Conferência Física ou Importação de NF (HTML/XML) ➔ Conversão de Embalagem ➔ Registro de Responsável, Data e Hora</p>
        </div>
    """, unsafe_allow_html=True)
    
    aba_manual, aba_nf = st.tabs(["📝 Entrada Manual em Lote", "📄 Importar HTML / XML da Nota Fiscal"])
    
    with aba_manual:
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
                        "GRUPO": p_row["GRUPO"],
                        "QTD_TOTAL_ENTRADA": qtd_final,
                        "UNIDADE": p_row["UND_VENDA"]
                    })
                    st.success(f"Incluído no lote: {p_row['DESCRICAO']} (+{qtd_final} {p_row['UND_VENDA']})")
                    
        if len(st.session_state.carrinho_entrada) > 0:
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
                    
                    conn = conectar_db()
                    cur = conn.cursor()
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
                    conn.commit()
                    conn.close()
                    limpar_caches()
                    st.session_state.carrinho_entrada = []
                    st.success(f"🎉 Entrada registrada! Protocolo: {id_rom} | Responsável: {nome_ent}")
                    st.rerun()
            if col_b2.button("🗑️ Limpar Lote", use_container_width=True):
                st.session_state.carrinho_entrada = []
                st.rerun()

    with aba_nf:
        st.write("Suba o arquivo **HTML** ou **XML** da Nota Fiscal para leitura automática dos itens.")
        resp_nf = st.text_input("👤 Responsável pela Importação da NF (Obrigatório):", value=operador, key="resp_nf_imp")
        arq_nf = st.file_uploader("Solte aqui o arquivo HTML ou XML da Nota Fiscal:", type=["html", "htm", "xml", "xls"])
        
        if arq_nf is not None:
            itens_extraidos = []
            nome_arq = arq_nf.name.lower()
            try:
                if nome_arq.endswith(".xml"):
                    tree = ET.parse(arq_nf)
                    root = tree.getroot()
                    for det in root.iter():
                        if det.tag.endswith("prod"):
                            cProd, cEAN, xProd, qCom, uCom = "", "", "", 0.0, ""
                            for child in det:
                                tag = child.tag.split("}")[-1]
                                if tag == "cProd": cProd = child.text or ""
                                elif tag == "cEAN": cEAN = child.text or ""
                                elif tag == "xProd": xProd = child.text or ""
                                elif tag == "qCom": qCom = float(child.text or 0)
                                elif tag == "uCom": uCom = child.text or ""
                            itens_extraidos.append({"COD_NF": cProd, "EAN_NF": cEAN, "PRODUTO_NF": xProd, "QTD_NF": qCom, "UND_NF": uCom})
                else:
                    conteudo = arq_nf.read().decode("utf-8", errors="ignore")
                    tabelas = pd.read_html(conteudo, decimal=",", thousands=".")
                    for t in tabelas:
                        if t.shape[1] >= 3 and len(t) >= 1:
                            itens_extraidos.append(t)
                            
                if nome_arq.endswith(".xml") and len(itens_extraidos) > 0:
                    df_nf = pd.DataFrame(itens_extraidos)
                    st.success(f"Foram identificados {len(df_nf)} produtos no XML da Nota Fiscal!")
                    itens_para_confirmar = []
                    for idx, row in df_nf.iterrows():
                        match = df_produtos[(df_produtos["COD_BARRAS"] == str(row["EAN_NF"])) & (df_produtos["COD_BARRAS"] != "") & (df_produtos["COD_BARRAS"] != "SEM GTIN")]
                        default_idx = 0
                        if len(match) > 0:
                            cod_m = match.iloc[0]["CODIGO"]
                            for i_op, op in enumerate(opcoes_busca):
                                if op.startswith(cod_m + " |"):
                                    default_idx = i_op
                                    break
                        c_nf1, c_nf2, c_nf3 = st.columns([2, 2, 1])
                        c_nf1.markdown(f"**NF:** {row['PRODUTO_NF']} <br><small>EAN: {row['EAN_NF']} | Cód: {row['COD_NF']}</small>", unsafe_allow_html=True)
                        vinc = c_nf2.selectbox(f"Vincular ao Catálogo (Item {idx+1}):", options=opcoes_busca, index=default_idx, key=f"vinc_{idx}")
                        qtd_vinc = c_nf3.number_input("Qtd a Somar:", value=float(row["QTD_NF"]), min_value=0.0, key=f"qvinc_{idx}")
                        if vinc != "" and qtd_vinc > 0:
                            cod_escolhido = vinc.split(" | ")[0]
                            p_esc = df_produtos[df_produtos["CODIGO"] == cod_escolhido].iloc[0]
                            itens_para_confirmar.append({
                                "CODIGO": cod_escolhido,
                                "COD_BARRAS": p_esc["COD_BARRAS"],
                                "DESCRICAO": p_esc["DESCRICAO"],
                                "GRUPO": p_esc["GRUPO"],
                                "QTD": qtd_vinc,
                                "UNIDADE": p_esc["UND_VENDA"]
                            })
                    if st.button("✅ Lançar Todos os Itens Vinculados da NF no Estoque", type="primary"):
                        if not resp_nf.strip():
                            st.error("🚫 Informe o nome do Responsável pela Importação da NF acima!")
                        else:
                            nome_nf = resp_nf.strip().upper()
                            id_rom = "NF-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                            data_str = date.today().strftime("%Y-%m-%d")
                            data_br = date.today().strftime("%d/%m/%Y")
                            hora_str = datetime.now().strftime("%H:%M:%S")
                            data_hora_str = f"{data_br} {hora_str}"
                            conn = conectar_db()
                            cur = conn.cursor()
                            for it in itens_para_confirmar:
                                cur.execute("""
                                    UPDATE produtos 
                                    SET SALDO_DEPOSITO = SALDO_DEPOSITO + ?,
                                        ULTIMA_MOV_DATA = ?,
                                        ULTIMA_MOV_HORA = ?,
                                        ULTIMO_OPERADOR = ?
                                    WHERE CODIGO = ?
                                """, (it["QTD"], data_str, hora_str, nome_nf, it["CODIGO"]))
                                cur.execute("""
                                    INSERT INTO movimentacoes 
                                    (id_romaneio, data_registro, hora_registro, data_hora, tipo_operacao, motivo_destino, codigo_produto, cod_barras, descricao, grupo, quantidade, unidade, responsavel, nf_numero, observacao, caminho_foto)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (id_rom, data_str, hora_str, data_hora_str, "ENTRADA NF", "Importação Automática NF", it["CODIGO"], it["COD_BARRAS"], it["DESCRICAO"], it["GRUPO"], it["QTD"], it["UNIDADE"], nome_nf, arq_nf.name, "Importado via arquivo NF", ""))
                            conn.commit()
                            conn.close()
                            limpar_caches()
                            st.success(f"Entrada da Nota Fiscal concluída por {nome_nf}!")
                            st.rerun()
                elif len(itens_extraidos) > 0:
                    st.info("Tabelas encontradas no arquivo HTML da Nota Fiscal:")
                    for idx_t, tab in enumerate(itens_extraidos):
                        with st.expander(f"Tabela {idx_t+1} ({len(tab)} linhas)", expanded=(idx_t==0)):
                            st.dataframe(tab, use_container_width=True)
            except Exception as e:
                st.error(f"Erro ao ler arquivo: {e}")

# ==============================================================================
# TELA 3: RELATÓRIO DE ESTOQUE, FILTRO POR DATA E PESSOA E DOWNLOAD SOB DEMANDA
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
    
    termo = f1.text_input("🔎 Buscar por Nome, Código ou EAN:")
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
            df_view["COD_BARRAS"].str.contains(t_up, na=False)
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
        "CODIGO", "COD_BARRAS", "DESCRICAO", "GRUPO", "UND_VENDA",
        "SALDO_DEPOSITO", "SALDO_LOJA", "ESTOQUE_MINIMO", "STATUS_ESTOQUE",
        "ULTIMA_MOV_DATA", "ULTIMA_MOV_HORA", "ULTIMO_OPERADOR", "PRECO_VENDA", "FORNECEDOR"
    ]
    
    st.markdown(f"**Exibindo {len(df_view)} produtos filtrados:**")
    st.dataframe(df_view[colunas_relatorio], use_container_width=True, hide_index=True, height=420)
    
    # Download instantâneo em CSV e geração de Excel sob demanda (para não travar a tela a cada filtro)
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
# TELA 4: ABA COM GRÁFICOS PARA FILTRAR QUANTIDADE DE ESTOQUE POR GRUPO
# ==============================================================================
elif menu.startswith("📊"):
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
# TELA 5: AUDITORIA DE MOVIMENTAÇÕES E AVARIAS
# ==============================================================================
elif menu.startswith("📸"):
    st.markdown("""
        <div class="process-header">
            <h2>📸 Histórico de Movimentações e Auditoria de Avarias</h2>
            <p>Rastreabilidade total de quem retirou ou deu entrada, com filtro por Data, Hora, Pessoa e Galeria de Fotos de Avarias</p>
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
            "Apenas Entradas"
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
            df_m_view = df_m_view[df_m_view["tipo_operacao"].str.contains("ENTRADA", na=False)]
            
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

# ==============================================================================
# TELA 6: CADASTRAR PRODUTO E DEFINIR ESTOQUE MÍNIMO DE SEGURANÇA (LOTE E INDIVIDUAL)
# ==============================================================================
elif menu.startswith("⚙️"):
    st.markdown("""
        <div class="process-header">
            <h2>⚙️ Parametrização de Estoque Mínimo de Segurança (Individual e em Lote) e Cadastro</h2>
            <p>Defina o estoque mínimo de segurança por produto, aplique em lote por Grupo/Família, edite diretamente na tabela ou cadastre novos SKUs</p>
        </div>
    """, unsafe_allow_html=True)
    
    aba_lote, aba_minimo, aba_novo = st.tabs([
        "📦 1. Definir Estoque Mínimo em Lote (Por Grupo ou Tabela)",
        "🛡️ 2. Ajuste Individual de Produto",
        "➕ 3. Cadastrar Novo Produto"
    ])
    
    with aba_lote:
        st.markdown('<span class="step-badge">OPÇÃO A: APLICAR ESTOQUE MÍNIMO EM LOTE POR GRUPO DE PRODUTOS</span>', unsafe_allow_html=True)
        grupos_todos = sorted(df_produtos["GRUPO"].unique().tolist())
        with st.form("form_minimo_lote_grupo"):
            cl1, cl2, cl3 = st.columns([2.2, 1.3, 1])
            grupos_lote = cl1.multiselect(
                "Selecione o(s) Grupo(s) de Produtos:",
                options=grupos_todos,
                placeholder="Ex: ISOPOR:CAIXAS, PAPELAO, DESCARTAVEL:SACOLAS..."
            )
            modo_aplicacao = cl2.radio(
                "Regra de Aplicação:",
                [
                    "Aplicar em todos os produtos do grupo",
                    "Apenas nos que têm Estoque Mínimo <= 5"
                ]
            )
            valor_minimo_lote = cl3.number_input(
                "🛡️ Novo Estoque Mínimo para o Grupo:",
                min_value=0.0,
                value=20.0,
                step=5.0
            )
            
            if st.form_submit_button("🚀 Aplicar Estoque Mínimo em Lote aos Grupos Selecionados", type="primary", use_container_width=True):
                if len(grupos_lote) == 0:
                    st.warning("⚠️ Selecione pelo menos um Grupo de Produtos antes de aplicar.")
                else:
                    conn = conectar_db()
                    cur = conn.cursor()
                    placeholders = ",".join(["?"] * len(grupos_lote))
                    if "Apenas" in modo_aplicacao:
                        query_lote = f"UPDATE produtos SET ESTOQUE_MINIMO = ? WHERE GRUPO IN ({placeholders}) AND ESTOQUE_MINIMO <= 5"
                    else:
                        query_lote = f"UPDATE produtos SET ESTOQUE_MINIMO = ? WHERE GRUPO IN ({placeholders})"
                    cur.execute(query_lote, [valor_minimo_lote] + grupos_lote)
                    qtd_afetada = cur.rowcount
                    conn.commit()
                    conn.close()
                    limpar_caches()
                    st.success(f"✅ Estoque Mínimo atualizado em lote para {valor_minimo_lote} unidades em {qtd_afetada} produtos!")
                    st.rerun()
                    
        st.divider()
        st.markdown('<span class="step-badge">OPÇÃO B: EDIÇÃO RÁPIDA DIRETA NA TABELA (TIPO PLANILHA)</span>', unsafe_allow_html=True)
        filtro_grp_ed = st.selectbox("Filtrar Grupo para Edição na Tabela:", options=["Mostrar Top 100 Produtos"] + grupos_todos, key="grp_ed_tab")
        if filtro_grp_ed == "Mostrar Top 100 Produtos":
            df_para_editar = df_produtos[["CODIGO", "COD_BARRAS", "DESCRICAO", "GRUPO", "UND_VENDA", "SALDO_DEPOSITO", "ESTOQUE_MINIMO", "STATUS_ESTOQUE"]].head(100).copy()
        else:
            df_para_editar = df_produtos[df_produtos["GRUPO"] == filtro_grp_ed][["CODIGO", "COD_BARRAS", "DESCRICAO", "GRUPO", "UND_VENDA", "SALDO_DEPOSITO", "ESTOQUE_MINIMO", "STATUS_ESTOQUE"]].copy()
            
        df_editado = st.data_editor(
            df_para_editar,
            disabled=["CODIGO", "COD_BARRAS", "DESCRICAO", "GRUPO", "UND_VENDA", "STATUS_ESTOQUE"],
            use_container_width=True,
            hide_index=True,
            height=380,
            key="editor_lote_tabela"
        )
        
        if st.button("💾 Salvar Alterações da Tabela no Banco de Dados", type="primary"):
            conn = conectar_db()
            cur = conn.cursor()
            dados_batch = [
                (float(r_ed["SALDO_DEPOSITO"]), float(r_ed["ESTOQUE_MINIMO"]), str(r_ed["CODIGO"]))
                for _, r_ed in df_editado.iterrows()
            ]
            cur.executemany("UPDATE produtos SET SALDO_DEPOSITO = ?, ESTOQUE_MINIMO = ? WHERE CODIGO = ?", dados_batch)
            conn.commit()
            conn.close()
            limpar_caches()
            st.success(f"✅ {len(dados_batch)} registros atualizados instantaneamente!")
            st.rerun()

    with aba_minimo:
        st.subheader("🛡️ Ajustar Estoque Mínimo de Segurança Individualmente")
        prod_ajuste = st.selectbox(
            "Selecione o Produto para parametrizar:",
            options=opcoes_busca,
            key="sel_minimo"
        )
        
        if prod_ajuste != "":
            cod_aj = prod_ajuste.split(" | ")[0]
            linha_p = df_produtos[df_produtos["CODIGO"] == cod_aj].iloc[0]
            
            c_i1, c_i2, c_i3 = st.columns(3)
            c_i1.metric("Saldo Atual no Depósito", f"{linha_p['SALDO_DEPOSITO']} {linha_p['UND_VENDA']}")
            c_i2.metric("Estoque Mínimo Atual", f"{linha_p['ESTOQUE_MINIMO']} {linha_p['UND_VENDA']}")
            c_i3.metric("Diagnóstico Atual", linha_p["STATUS_ESTOQUE"])
            
            with st.form("form_atualizar_minimo"):
                cm1, cm2, cm3 = st.columns(3)
                novo_minimo = cm1.number_input(
                    "🛡️ Novo Estoque Mínimo de Segurança:",
                    min_value=0.0,
                    value=float(linha_p["ESTOQUE_MINIMO"]),
                    step=1.0
                )
                novo_saldo_dep = cm2.number_input(
                    "📦 Saldo Físico no Depósito (Inventário):",
                    value=float(linha_p["SALDO_DEPOSITO"]),
                    step=1.0
                )
                novo_grupo_aj = cm3.text_input("Grupo do Produto:", value=str(linha_p["GRUPO"]))
                
                if st.form_submit_button("💾 Salvar Estoque Mínimo de Segurança", type="primary"):
                    conn = conectar_db()
                    cur = conn.cursor()
                    cur.execute("""
                        UPDATE produtos 
                        SET ESTOQUE_MINIMO = ?, SALDO_DEPOSITO = ?, GRUPO = ?
                        WHERE CODIGO = ?
                    """, (novo_minimo, novo_saldo_dep, novo_grupo_aj.upper(), cod_aj))
                    conn.commit()
                    conn.close()
                    limpar_caches()
                    st.success(f"✅ Estoque Mínimo do produto '{linha_p['DESCRICAO']}' atualizado para {novo_minimo} {linha_p['UND_VENDA']}!")
                    st.rerun()

    with aba_novo:
        st.subheader("➕ Cadastrar Novo SKU no Catálogo")
        with st.form("novo_prod_v4"):
            c1, c2, c3 = st.columns(3)
            novo_cod = c1.text_input("Código Interno (Ex: 002876):")
            novo_ean = c2.text_input("Código de Barras (EAN):")
            nova_und = c3.selectbox("Unidade de Controle:", ["UN", "CX", "PCT", "FD", "KGS", "MLH", "RL"])
            nova_desc = st.text_input("Descrição Completa do Produto:")
            c4, c5, c6, c7 = st.columns(4)
            novo_grupo = c4.text_input("Grupo (Ex: DESCARTAVEL:SACOLAS):", value="GERAL")
            novo_saldo = c5.number_input("Saldo Inicial no Depósito:", value=0.0)
            novo_est_min = c6.number_input("🛡️ Estoque Mínimo de Segurança:", min_value=0.0, value=10.0)
            novo_preco = c7.number_input("Preço de Venda (R$):", min_value=0.0, value=0.0)
            
            if st.form_submit_button("💾 Salvar Novo Produto no Catálogo", type="primary"):
                if not novo_cod or not nova_desc:
                    st.error("Preencha obrigatoriamente o Código e a Descrição do produto!")
                else:
                    conn = conectar_db()
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO produtos 
                        (CODIGO, COD_BARRAS, DESCRICAO, UND_VENDA, UND_COMPRA, FATOR_CONVERSAO, GRUPO, FORNECEDOR, SALDO_DEPOSITO, SALDO_LOJA, ESTOQUE_MINIMO, PRECO_VENDA, SITUACAO, ULTIMA_MOV_DATA, ULTIMA_MOV_HORA, ULTIMO_OPERADOR)
                        VALUES (?, ?, ?, ?, ?, 1.0, ?, 'CADASTRO MANUAL', ?, 0.0, ?, ?, 'Ativo', ?, ?, ?)
                    """, (
                        novo_cod.zfill(6), novo_ean, nova_desc.upper(), nova_und, nova_und,
                        novo_grupo.upper(), novo_saldo, novo_est_min, novo_preco,
                        date.today().strftime("%Y-%m-%d"), datetime.now().strftime("%H:%M:%S"),
                        operador.strip().upper() if operador.strip() else "SISTEMA"
                    ))
                    conn.commit()
                    conn.close()
                    limpar_caches()
                    st.success(f"✅ Produto '{nova_desc.upper()}' cadastrado com Estoque Mínimo de {novo_est_min} {nova_und}!")
                    st.rerun()
