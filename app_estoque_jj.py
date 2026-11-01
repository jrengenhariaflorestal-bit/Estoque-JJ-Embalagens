import streamlit as st
import pandas as pd
import sqlite3
import os
from datetime import datetime
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

# Configuração da Página (Adaptada para Telemóvel e Computador)
st.set_page_config(
    page_title="JJ Embalagens - Gestão de Stock",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Diretórios e Base de Dados
DB_FILE = "estoque_jj.db"
CSV_INICIAL = "produtos_jj_embalagens.csv"
PASTA_FOTOS = "fotos_avarias"
os.makedirs(PASTA_FOTOS, exist_ok=True)

# Estilo Visual com as cores da JJ Embalagens (Vermelho #9E1B1B e Dourado #F5B041)
st.markdown("""
    <style>
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
    }
    div[data-testid="stMetricValue"] {
        color: #9E1B1B;
    }
    </style>
""", unsafe_allow_html=True)

def conectar_db():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def inicializar_banco():
    conn = conectar_db()
    cursor = conn.cursor()
    
    # Tabela de Movimentações (Kardex / Romaneios)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_romaneio TEXT,
            data_hora TEXT,
            tipo_operacao TEXT,
            motivo_destino TEXT,
            codigo_produto TEXT,
            cod_barras TEXT,
            descricao TEXT,
            quantidade REAL,
            unidade TEXT,
            responsavel TEXT,
            nf_numero TEXT,
            observacao TEXT,
            caminho_foto TEXT
        )
    """)
    conn.commit()
    
    # Verifica se a tabela de produtos já existe
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='produtos'")
    if not cursor.fetchone():
        if os.path.exists(CSV_INICIAL):
            df_init = pd.read_csv(CSV_INICIAL, dtype={'CODIGO': str, 'COD_BARRAS': str})
            df_init['CODIGO'] = df_init['CODIGO'].str.zfill(6)
            df_init.to_sql("produtos", conn, if_exists="replace", index=False)
    conn.close()

inicializar_banco()

# Inicialização dos Carrinhos na Sessão (Retirada Múltipla e Entrada Múltipla)
if "carrinho_saida" not in st.session_state:
    st.session_state.carrinho_saida = []
if "carrinho_entrada" not in st.session_state:
    st.session_state.carrinho_entrada = []

def carregar_produtos():
    conn = conectar_db()
    df = pd.read_sql("SELECT * FROM produtos", conn)
    conn.close()
    return df

# Barra Lateral com Logomarca e Menu
with st.sidebar:
    if os.path.exists("logo.png"):
        st.image("logo.png", use_container_width=True)
    else:
        st.title("📦 JJ EMBALAGENS")
    st.caption("Economia, Qualidade e Variedade")
    st.divider()
    
    operador = st.text_input("👤 Nome do Operador / Responsável:", value="Operador Estoque")
    
    menu = st.radio(
        "Navegação do Sistema:",
        [
            "📤 1. Dar Baixa / Retirada (Múltipla)",
            "📥 2. Entrada (Manual ou HTML/XML NF)",
            "🔍 3. Consultar Stock e Prateleiras",
            "📸 4. Histórico e Auditoria de Avarias",
            "⚙️ 5. Cadastrar / Ajustar Produto"
        ]
    )

df_produtos = carregar_produtos()
# Cria coluna combinada para pesquisa rápida por Código, Código de Barras ou Nome
df_produtos["BUSCA_RAPIDA"] = (
    df_produtos["CODIGO"].astype(str) + " | " +
    df_produtos["DESCRICAO"].astype(str) + " | EAN: " +
    df_produtos["COD_BARRAS"].astype(str) + " (Saldo: " +
    df_produtos["SALDO_DEPOSITO"].round(1).astype(str) + " " +
    df_produtos["UND_VENDA"].astype(str) + ")"
)

# ==============================================================================
# TELA 1: DAR BAIXA / RETIRADA MÚLTIPLA (CESTA DE SAÍDA)
# ==============================================================================
if menu.startswith("📤"):
    st.header("📤 Dar Baixa no Stock (Retirada Múltipla)")
    st.write("Adicione um ou vários produtos à lista de retirada e confirme a baixa de todos de uma só vez.")
    
    col_busca, col_qtd, col_btn = st.columns([3, 1, 1])
    
    with col_busca:
        item_selecionado = st.selectbox(
            "Pesquise pelo Código, Código de Barras ou Nome do Produto:",
            options=[""] + df_produtos["BUSCA_RAPIDA"].tolist(),
            index=0
        )
    with col_qtd:
        qtd_retirada = st.number_input("Quantidade a retirar:", min_value=0.01, value=1.0, step=1.0)
    with col_btn:
        st.write("")
        st.write("")
        if st.button("➕ Adicionar à Lista", use_container_width=True, type="primary"):
            if item_selecionado == "":
                st.warning("Selecione um produto antes de adicionar.")
            else:
                cod_sel = item_selecionado.split(" | ")[0]
                prod_row = df_produtos[df_produtos["CODIGO"] == cod_sel].iloc[0]
                st.session_state.carrinho_saida.append({
                    "CODIGO": prod_row["CODIGO"],
                    "COD_BARRAS": prod_row["COD_BARRAS"],
                    "DESCRICAO": prod_row["DESCRICAO"],
                    "QUANTIDADE": float(qtd_retirada),
                    "UNIDADE": prod_row["UND_VENDA"],
                    "SALDO_ATUAL": float(prod_row["SALDO_DEPOSITO"])
                })
                st.success(f"Adicionado: {prod_row['DESCRICAO']} ({qtd_retirada} {prod_row['UND_VENDA']})")

    st.divider()
    
    # Exibição do Carrinho de Retirada
    st.subheader(f"🛒 Lista de Produtos para Baixa ({len(st.session_state.carrinho_saida)} itens)")
    
    if len(st.session_state.carrinho_saida) == 0:
        st.info("Nenhum produto na lista. Pesquise acima e clique em 'Adicionar à Lista' para empilhar os produtos que vai retirar do stock.")
    else:
        df_cesta = pd.DataFrame(st.session_state.carrinho_saida)
        st.dataframe(df_cesta, use_container_width=True, hide_index=True)
        
        col_limpar, _ = st.columns([1, 4])
        if col_limpar.button("🗑️ Limpar Lista"):
            st.session_state.carrinho_saida = []
            st.rerun()
            
        st.markdown("### Finalizar Baixa do Romaneio")
        col_dest, col_obs = st.columns(2)
        
        with col_dest:
            motivo = st.radio(
                "Qual é o destino/motivo desta retirada?",
                [
                    "🏪 Reposição nas Prateleiras da Loja",
                    "🚚 Expedição / Venda Direta ao Cliente",
                    "⚠️ Baixa por Avaria / Produto Danificado",
                    "🔧 Consumo Interno / Ajuste"
                ]
            )
            
        with col_obs:
            observacao = st.text_area(
                "Observações (Obrigatório detallhar em caso de avaria ou informar corredor/prateleira):",
                placeholder="Ex: Caixa molhada no transporte / Reposição corredor central da loja..."
            )
            
        # Regra de Negócio: Se for Avaria, obriga a inserir foto (Câmara do Telemóvel ou Galeria)
        foto_avaria = None
        if "Avaria" in motivo:
            st.error("📸 **ATENÇÃO:** Para baixa por **Avaria**, é OBRIGATÓRIO anexar a fotografia dos produtos avariados e preencher a observação!")
            metodo_foto = st.radio("Como deseja inserir a fotografia da avaria?", ["📁 Enviar da Galeria / Computador", "📷 Tirar Fotografia Agora (Telemóvel/Webcam)"], horizontal=True)
            if "Galeria" in metodo_foto:
                foto_avaria = st.file_uploader("Selecione a imagem do produto avariado (JPG/PNG):", type=["jpg", "jpeg", "png"])
            else:
                foto_avaria = st.camera_input("Aponte a câmara para o produto avariado:")
                
        if st.button("✅ Confirmar Baixa de Todos os Produtos da Lista", type="primary", use_container_width=True):
            if not operador.strip():
                st.error("Informe o nome do Operador na barra lateral.")
            elif "Avaria" in motivo and (foto_avaria is None or not observacao.strip()):
                st.error("🚫 BLOQUEADO: Para dar baixa por avaria, é obrigatório anexar a fotografia da avaria e escrever a descrição do problema no campo de observações!")
            else:
                id_rom = "ROM-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                data_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                caminho_salvo = ""
                
                if foto_avaria is not None:
                    caminho_salvo = os.path.join(PASTA_FOTOS, f"{id_rom}.jpg")
                    with open(caminho_salvo, "wb") as f:
                        f.write(foto_avaria.getbuffer())
                        
                conn = conectar_db()
                cur = conn.cursor()
                
                for item in st.session_state.carrinho_saida:
                    # Desconta do Saldo do Depósito
                    cur.execute(
                        "UPDATE produtos SET SALDO_DEPOSITO = SALDO_DEPOSITO - ? WHERE CODIGO = ?",
                        (item["QUANTIDADE"], item["CODIGO"])
                    )
                    # Se foi Reposição nas Prateleiras da Loja, soma no SALDO_LOJA
                    if "Prateleiras da Loja" in motivo:
                        cur.execute(
                            "UPDATE produtos SET SALDO_LOJA = SALDO_LOJA + ? WHERE CODIGO = ?",
                            (item["QUANTIDADE"], item["CODIGO"])
                        )
                    # Regista no Histórico (Kardex)
                    cur.execute("""
                        INSERT INTO movimentacoes 
                        (id_romaneio, data_hora, tipo_operacao, motivo_destino, codigo_produto, cod_barras, descricao, quantidade, unidade, responsavel, nf_numero, observacao, caminho_foto)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        id_rom, data_atual, "SAÍDA", motivo, item["CODIGO"], item["COD_BARRAS"],
                        item["DESCRICAO"], item["QUANTIDADE"], item["UNIDADE"], operador, "", observacao, caminho_salvo
                    ))
                conn.commit()
                conn.close()
                st.session_state.carrinho_saida = []
                st.success(f"🎉 Baixa concluída com sucesso! Romaneio gerado: {id_rom}")
                st.rerun()

# ==============================================================================
# TELA 2: ENTRADA DE PRODUTOS (MANUAL EM LOTE OU FICHEIRO HTML/XML DA NOTA FISCAL)
# ==============================================================================
elif menu.startswith("📥"):
    st.header("📥 Entrada de Mercadorias no Stock")
    aba_manual, aba_nf = st.tabs(["📝 Entrada Manual (Múltiplos Produtos)", "📄 Importar HTML / XML da Nota Fiscal"])
    
    with aba_manual:
        st.write("Adicione os produtos recebidos à lista de entrada e confirme o recebimento em lote.")
        c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
        with c1:
            prod_ent = st.selectbox("Produto recebido:", options=[""] + df_produtos["BUSCA_RAPIDA"].tolist(), key="ent_sel")
        with c2:
            qtd_ent = st.number_input("Qtd Recebida:", min_value=0.01, value=1.0, step=1.0, key="ent_qtd")
        with c3:
            fator_mult = st.number_input("Unidades por Fardo/Caixa:", min_value=1.0, value=1.0, step=1.0, help="Se comprou 5 caixas com 100 unidades cada e controla por unidade, coloque 100 aqui.")
        with c4:
            st.write("")
            st.write("")
            if st.button("➕ Incluir na Entrada", use_container_width=True, type="primary"):
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
                        "QTD_TOTAL_ENTRADA": qtd_final,
                        "UNIDADE": p_row["UND_VENDA"]
                    })
                    
        if len(st.session_state.carrinho_entrada) > 0:
            st.dataframe(pd.DataFrame(st.session_state.carrinho_entrada), use_container_width=True, hide_index=True)
            nf_man = st.text_input("Número da Nota Fiscal / Pedido (Opcional):")
            obs_man = st.text_input("Observação da Entrada (Fornecedor / Transportadora):")
            
            col_b1, col_b2 = st.columns([2, 1])
            if col_b1.button("✅ Confirmar Entrada no Stock", type="primary", use_container_width=True):
                id_rom = "ENT-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                data_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                conn = conectar_db()
                cur = conn.cursor()
                for item in st.session_state.carrinho_entrada:
                    cur.execute(
                        "UPDATE produtos SET SALDO_DEPOSITO = SALDO_DEPOSITO + ? WHERE CODIGO = ?",
                        (item["QTD_TOTAL_ENTRADA"], item["CODIGO"])
                    )
                    cur.execute("""
                        INSERT INTO movimentacoes 
                        (id_romaneio, data_hora, tipo_operacao, motivo_destino, codigo_produto, cod_barras, descricao, quantidade, unidade, responsavel, nf_numero, observacao, caminho_foto)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        id_rom, data_atual, "ENTRADA", "Entrada Manual / Recebimento", item["CODIGO"], item["COD_BARRAS"],
                        item["DESCRICAO"], item["QTD_TOTAL_ENTRADA"], item["UNIDADE"], operador, nf_man, obs_man, ""
                    ))
                conn.commit()
                conn.close()
                st.session_state.carrinho_entrada = []
                st.success(f"🎉 Entrada registada com sucesso! Protocolo: {id_rom}")
                st.rerun()
            if col_b2.button("🗑️ Limpar Lista de Entrada", use_container_width=True):
                st.session_state.carrinho_entrada = []
                st.rerun()

    with aba_nf:
        st.write("Carregue o ficheiro **HTML** (DANFE/SEFAZ/Relatório ERP) ou **XML** da Nota Fiscal para ler os itens automaticamente.")
        arq_nf = st.file_uploader("Solte aqui o ficheiro HTML ou XML da Nota Fiscal:", type=["html", "htm", "xml", "xls"])
        
        if arq_nf is not None:
            itens_extraidos = []
            nome_arq = arq_nf.name.lower()
            
            try:
                if nome_arq.endswith(".xml"):
                    tree = ET.parse(arq_nf)
                    root = tree.getroot()
                    for det in root.iter():
                        if det.tag.endswith("prod"):
                            cProd = ""
                            cEAN = ""
                            xProd = ""
                            qCom = 0.0
                            uCom = ""
                            for child in det:
                                tag = child.tag.split("}")[-1]
                                if tag == "cProd": cProd = child.text or ""
                                elif tag == "cEAN": cEAN = child.text or ""
                                elif tag == "xProd": xProd = child.text or ""
                                elif tag == "qCom": qCom = float(child.text or 0)
                                elif tag == "uCom": uCom = child.text or ""
                            itens_extraidos.append({
                                "COD_NF": cProd,
                                "EAN_NF": cEAN,
                                "PRODUTO_NF": xProd,
                                "QTD_NF": qCom,
                                "UND_NF": uCom
                            })
                else:
                    # Leitura de HTML de Nota Fiscal (Tabelas da SEFAZ / DANFE / ERP)
                    conteudo = arq_nf.read().decode("utf-8", errors="ignore")
                    tabelas = pd.read_html(conteudo, decimal=",", thousands=".")
                    for t in tabelas:
                        if t.shape[1] >= 3 and len(t) >= 1:
                            t_str = t.astype(str)
                            # Procura colunas com nomes de produtos ou quantidades
                            itens_extraidos.append(t)
                            
                if nome_arq.endswith(".xml") and len(itens_extraidos) > 0:
                    df_nf = pd.DataFrame(itens_extraidos)
                    st.success(f"Foram encontrados {len(df_nf)} produtos na Nota Fiscal!")
                    
                    st.write("Confira e associe os itens da NF aos produtos do catálogo JJ Embalagens:")
                    itens_para_confirmar = []
                    for idx, row in df_nf.iterrows():
                        # Tenta achar pelo Código de Barras (EAN) ou Código do Fabricante
                        match = df_produtos[
                            (df_produtos["COD_BARRAS"] == str(row["EAN_NF"])) & 
                            (df_produtos["COD_BARRAS"] != "") &
                            (df_produtos["COD_BARRAS"] != "SEM GTIN")
                        ]
                        default_idx = 0
                        if len(match) > 0:
                            cod_m = match.iloc[0]["CODIGO"]
                            opcoes_lista = [""] + df_produtos["BUSCA_RAPIDA"].tolist()
                            for i_op, op in enumerate(opcoes_lista):
                                if op.startswith(cod_m + " |"):
                                    default_idx = i_op
                                    break
                        
                        c_nf1, c_nf2, c_nf3 = st.columns([2, 2, 1])
                        c_nf1.markdown(f"**NF:** {row['PRODUTO_NF']} <br><small>EAN: {row['EAN_NF']} | Cód: {row['COD_NF']}</small>", unsafe_allow_html=True)
                        vinc = c_nf2.selectbox(f"Vincular ao Stock (Item {idx+1}):", options=[""] + df_produtos["BUSCA_RAPIDA"].tolist(), index=default_idx, key=f"vinc_{idx}")
                        qtd_vinc = c_nf3.number_input("Qtd a Somar:", value=float(row["QTD_NF"]), min_value=0.0, key=f"qvinc_{idx}")
                        if vinc != "" and qtd_vinc > 0:
                            cod_escolhido = vinc.split(" | ")[0]
                            p_esc = df_produtos[df_produtos["CODIGO"] == cod_escolhido].iloc[0]
                            itens_para_confirmar.append({
                                "CODIGO": cod_escolhido,
                                "COD_BARRAS": p_esc["COD_BARRAS"],
                                "DESCRICAO": p_esc["DESCRICAO"],
                                "QTD": qtd_vinc,
                                "UNIDADE": p_esc["UND_VENDA"]
                            })
                    if st.button("✅ Lançar Todos os Itens Vinculados da NF no Stock", type="primary"):
                        id_rom = "NF-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                        data_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                        conn = conectar_db()
                        cur = conn.cursor()
                        for it in itens_para_confirmar:
                            cur.execute("UPDATE produtos SET SALDO_DEPOSITO = SALDO_DEPOSITO + ? WHERE CODIGO = ?", (it["QTD"], it["CODIGO"]))
                            cur.execute("""
                                INSERT INTO movimentacoes 
                                (id_romaneio, data_hora, tipo_operacao, motivo_destino, codigo_produto, cod_barras, descricao, quantidade, unidade, responsavel, nf_numero, observacao, caminho_foto)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (id_rom, data_atual, "ENTRADA NF", "Importação Automática NF", it["CODIGO"], it["COD_BARRAS"], it["DESCRICAO"], it["QTD"], it["UNIDADE"], operador, arq_nf.name, "Importado via ficheiro NF", ""))
                        conn.commit()
                        conn.close()
                        st.success(f"Entrada da Nota Fiscal concluída ({len(itens_para_confirmar)} itens somados ao stock)!")
                        st.rerun()
                elif len(itens_extraidos) > 0:
                    st.info("Tabelas identificadas no ficheiro HTML da Nota Fiscal:")
                    for idx_t, tab in enumerate(itens_extraidos):
                        with st.expander(f"Tabela {idx_t+1} da Nota Fiscal ({len(tab)} linhas)", expanded=(idx_t==0)):
                            st.dataframe(tab, use_container_width=True)
                    st.caption("Dica: Selecione os itens na aba 'Entrada Manual' ao lado ou envie o ficheiro .XML/HTML padrão SEFAZ para vínculo automático por EAN.")
                else:
                    st.warning("Não foram encontradas tabelas de produtos no ficheiro enviado.")
            except Exception as e:
                st.error(f"Erro ao processar o ficheiro da Nota Fiscal: {e}")

# ==============================================================================
# TELA 3: CONSULTAR STOCK E PRATELEIRAS DA LOJA
# ==============================================================================
elif menu.startswith("🔍"):
    st.header("🔍 Consulta de Saldo em Stock (Depósito vs. Loja)")
    
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total de SKUs Cadastrados", f"{len(df_produtos):,}".replace(",", "."))
    k2.metric("Produtos Ativos", f"{len(df_produtos[df_produtos['SITUACAO']=='Ativo']):,}".replace(",", "."))
    k3.metric("Com Saldo no Depósito (>0)", f"{len(df_produtos[df_produtos['SALDO_DEPOSITO']>0]):,}".replace(",", "."))
    k4.metric("Abaixo do Mínimo (Repor)", f"{len(df_produtos[df_produtos['SALDO_DEPOSITO'] < df_produtos['ESTOQUE_MINIMO']]):,}".replace(",", "."))
    
    f1, f2, f3 = st.columns([2, 1, 1])
    termo = f1.text_input("🔎 Filtrar por Nome, Código ou Código de Barras:")
    grupo_sel = f2.selectbox("Filtrar por Grupo:", ["Todos"] + sorted(df_produtos["GRUPO"].unique().tolist()))
    status_filtro = f3.selectbox("Filtro de Saldo:", ["Todos", "Apenas Saldo Positivo (> 0)", "Apenas Saldo Zerado", "Abaixo do Stock Mínimo"])
    
    df_view = df_produtos.copy()
    if termo:
        termo_up = termo.upper()
        df_view = df_view[
            df_view["DESCRICAO"].astype(str).str.upper().str.contains(termo_up) |
            df_view["CODIGO"].astype(str).str.contains(termo_up) |
            df_view["COD_BARRAS"].astype(str).str.contains(termo_up)
        ]
    if grupo_sel != "Todos":
        df_view = df_view[df_view["GRUPO"] == grupo_sel]
    if status_filtro == "Apenas Saldo Positivo (> 0)":
        df_view = df_view[df_view["SALDO_DEPOSITO"] > 0]
    elif status_filtro == "Apenas Saldo Zerado":
        df_view = df_view[df_view["SALDO_DEPOSITO"] <= 0]
    elif status_filtro == "Abaixo do Stock Mínimo":
        df_view = df_view[df_view["SALDO_DEPOSITO"] < df_view["ESTOQUE_MINIMO"]]
        
    colunas_exibir = ["CODIGO", "COD_BARRAS", "DESCRICAO", "GRUPO", "UND_VENDA", "SALDO_DEPOSITO", "SALDO_LOJA", "ESTOQUE_MINIMO", "PRECO_VENDA", "FORNECEDOR"]
    st.dataframe(df_view[colunas_exibir], use_container_width=True, hide_index=True, height=500)

# ==============================================================================
# TELA 4: HISTÓRICO DE MOVIMENTAÇÕES E AUDITORIA DE AVARIAS (COM FOTOS)
# ==============================================================================
elif menu.startswith("📸"):
    st.header("📸 Histórico de Movimentações e Auditoria de Avarias")
    conn = conectar_db()
    df_mov = pd.read_sql("SELECT * FROM movimentacoes ORDER BY id DESC", conn)
    conn.close()
    
    if len(df_mov) == 0:
        st.info("Nenhuma movimentação registada ainda.")
    else:
        filtro_motivo = st.selectbox("Filtrar por Tipo/Motivo:", ["Todas as Movimentações", "Apenas Baixas por Avaria (com Foto)", "Apenas Reposição de Loja", "Apenas Entradas"])
        df_m_view = df_mov.copy()
        if "Avaria" in filtro_motivo:
            df_m_view = df_m_view[df_m_view["motivo_destino"].str.contains("Avaria", na=False)]
        elif "Loja" in filtro_motivo:
            df_m_view = df_m_view[df_m_view["motivo_destino"].str.contains("Loja", na=False)]
        elif "Entradas" in filtro_motivo:
            df_m_view = df_m_view[df_m_view["tipo_operacao"].str.contains("ENTRADA", na=False)]
            
        st.dataframe(df_m_view, use_container_width=True, hide_index=True)
        
        # Galeria de Auditoria de Fotos de Avarias
        df_fotos = df_m_view[df_m_view["caminho_foto"] != ""]
        if len(df_fotos) > 0:
            st.subheader("🔍 Registos Fotográficos de Produtos Avariados")
            for _, r_foto in df_fotos.iterrows():
                with st.expander(f"📸 {r_foto['data_hora']} | {r_foto['descricao']} (Qtd: {r_foto['quantidade']}) - Resp: {r_foto['responsavel']}"):
                    st.write(f"**Observação da Avaria:** {r_foto['observacao']}")
                    if os.path.exists(r_foto["caminho_foto"]):
                        st.image(r_foto["caminho_foto"], width=400)

# ==============================================================================
# TELA 5: CADASTRAR NOVO PRODUTO OU AJUSTAR SALDO INICIAL
# ==============================================================================
elif menu.startswith("⚙️"):
    st.header("⚙️ Cadastrar Novo Produto ou Ajustar Contagem")
    with st.form("novo_prod"):
        c1, c2, c3 = st.columns(3)
        novo_cod = c1.text_input("Código Interno (Ex: 002876):")
        novo_ean = c2.text_input("Código de Barras (EAN):")
        nova_und = c3.selectbox("Unidade:", ["UN", "CX", "PCT", "FD", "KGS", "MLH", "RL"])
        nova_desc = st.text_input("Descrição Completa do Produto:")
        c4, c5, c6 = st.columns(3)
        novo_grupo = c4.text_input("Grupo (Ex: DESCARTAVEL:SACOLAS):", value="GERAL")
        novo_saldo = c5.number_input("Saldo Inicial no Depósito:", value=0.0)
        novo_preco = c6.number_input("Preço de Venda (R$):", value=0.0)
        
        if st.form_submit_button("💾 Guardar Produto no Catálogo", type="primary"):
            if not novo_cod or not nova_desc:
                st.error("Preencha pelo menos o Código e a Descrição!")
            else:
                conn = conectar_db()
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO produtos (CODIGO, COD_BARRAS, DESCRICAO, UND_VENDA, UND_COMPRA, FATOR_CONVERSAO, GRUPO, FORNECEDOR, SALDO_DEPOSITO, SALDO_LOJA, ESTOQUE_MINIMO, PRECO_VENDA, SITUACAO)
                    VALUES (?, ?, ?, ?, ?, 1.0, ?, 'CADASTRO MANUAL', ?, 0.0, 5.0, ?, 'Ativo')
                """, (novo_cod.zfill(6), novo_ean, nova_desc.upper(), nova_und, nova_und, novo_grupo.upper(), novo_saldo, novo_preco))
                conn.commit()
                conn.close()
                st.success(f"Produto {nova_desc} cadastrado com sucesso!")
                st.rerun()
