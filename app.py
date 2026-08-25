import streamlit as st
import pandas as pd
import os
import datetime
import time
import base64
import streamlit.components.v1 as components
import calendar
import zipfile
import io
st.set_page_config(page_title="Suporte Smart - Enterprise", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
    <style>
        /* 1. Esconder menu superior e rodapé */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        
        /* 2. Transformar o emblema da Streamlit num fantasma (invisível e sem clique) */
        [class^="viewerBadge"] {
            display: none !important;
            opacity: 0 !important;
            pointer-events: none !important;
            z-index: -9999 !important;
        }
        
        /* 3. Bloquear o clique e a visão de qualquer link da plataforma */
        a[href*="streamlit.io"] {
            display: none !important;
            pointer-events: none !important;
            opacity: 0 !important;
            cursor: default !important;
        }
    </style>
    """, unsafe_allow_html=True)
from supabase import create_client, Client

# ==========================================
# 1. CONEXÃO SUPABASE E ESTADO (RESILIENTE)
# ==========================================
SUPABASE_URL = "https://gtpsbwrzprrabsqgmlim.supabase.co"
SUPABASE_KEY = "sb_publishable_JUOMceD80qpiR5QFhtA-HA_OANfJpU8"

@st.cache_resource
def init_connection():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_connection()

if 'autenticado' not in st.session_state:
    st.session_state.autenticado = False; st.session_state.perfil = None; st.session_state.usuario_nome = None
if 'menu_selecionado' not in st.session_state: st.session_state.menu_selecionado = "VENDAS"
if 'recibo' not in st.session_state: st.session_state.recibo = None
if 'carrinho' not in st.session_state: st.session_state.carrinho = []
if 'acessorios' not in st.session_state: st.session_state.acessorios = []
if 'caixa_travado' not in st.session_state: st.session_state.caixa_travado = False

# MÁQUINA: Cão de Guarda de Segurança
if st.session_state.perfil == "VENDEDOR" and st.session_state.menu_selecionado not in ["CLIENTES", "VENDAS"]:
    st.session_state.menu_selecionado = "VENDAS"

def resetar_pdv():
    st.session_state.carrinho = []; st.session_state.acessorios = []
    chaves_memoria = ['val_ent_fin', 'val_ent_cli', 'forma_pagto_sel', 'fin_sel', 'tipo_pgto_ent_sel', 'parc_ent_val', 'desc_pct', 'qtd_parc', 'parc_fin', 'rec_paymobi']
    for k in chaves_memoria:
        if k in st.session_state: del st.session_state[k]

def mudar_aba(nova_aba):
    st.session_state.menu_selecionado = nova_aba
    st.session_state.recibo = None

def formata_br(valor):
    try:
        if pd.isna(valor) or valor == "" or valor is None: return "0,00"
        return f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return "0,00"

def get_image_base64(path):
    with open(path, "rb") as image_file: return base64.b64encode(image_file.read()).decode()

def adicionar_dias_uteis(data_inicial, dias):
    data_atual = data_inicial
    while dias > 0:
        data_atual += datetime.timedelta(days=1)
        if data_atual.weekday() < 5: dias -= 1
    return data_atual

hoje = datetime.date.today()
pasta_do_projeto = os.path.dirname(os.path.abspath(__file__))

# ==========================================
# FUNÇÕES DE BANCO DE DADOS (PERFORMANCE NUVEM)
# ==========================================
def fetch_df(table_name, cols, order_by='id', limit=None):
    try:
        query = supabase.table(table_name).select("*").order(order_by, desc=False)
        if limit: query = query.limit(limit)
        res = query.execute()
        if res.data: return pd.DataFrame(res.data)
        return pd.DataFrame(columns=cols)
    except: return pd.DataFrame(columns=cols)

def carregar_config():
    df = fetch_df('config', ['chave', 'valor'])
    defaults = {"margem_celular_pct": 100.0, "margem_acessorio_pct": 100.0, "limite_custo_premium": 900.0, "brinde_sugerido": "Película 3D de Brinde", "comissao_celular_pct": 1.0, "comissao_acessorio_pct": 5.0, "dias_garantia": 90}
    for _, r in df.iterrows():
        try: defaults[r['chave']] = float(r['valor'])
        except: defaults[r['chave']] = r['valor']
    return defaults

def salvar_config(config_dict):
    for k, v in config_dict.items():
        ex = supabase.table('config').select("id").eq('chave', k).execute()
        if ex.data: supabase.table('config').update({'valor': str(v)}).eq('chave', k).execute()
        else: supabase.table('config').insert({'chave': k, 'valor': str(v)}).execute()

@st.cache_data(ttl=2) 
def carregar_financeiro():
    b = fetch_df('bancos', ['id', 'nome', 'saldo_inicial'])
    b.rename(columns={'id':'ID', 'nome':'Nome', 'saldo_inicial':'Saldo_Inicial'}, inplace=True)
    
    cp = fetch_df('contas_pagar', ['id', 'descricao', 'categoria', 'fornecedor', 'vencimento', 'valor', 'data_pagamento', 'status', 'conta_origem', 'repeticao'])
    cp.rename(columns={'id':'ID', 'descricao':'Descricao', 'categoria':'Categoria', 'fornecedor':'Fornecedor', 'vencimento':'Vencimento', 'valor':'Valor', 'data_pagamento':'Data_Pagamento', 'status':'Status', 'conta_origem':'Conta_Origem', 'repeticao':'Repeticao'}, inplace=True)
    
    cr = fetch_df('contas_receber', ['id', 'origem_cliente', 'descricao', 'vencimento', 'valor', 'data_pagamento', 'status', 'conta_destino'])
    cr.rename(columns={'id':'ID', 'origem_cliente':'Origem_Cliente', 'descricao':'Descricao', 'vencimento':'Vencimento', 'valor':'Valor', 'data_pagamento':'Data_Pagamento', 'status':'Status', 'conta_destino':'Conta_Destino'}, inplace=True)
    
    # MÁQUINA: Puxa o financeiro completo para DRE, mas limitaremos a renderização visual depois
    mov = fetch_df('movimentacoes', ['id', 'tipo', 'descricao', 'valor', 'data', 'categoria', 'conta', 'status'])
    mov.rename(columns={'id':'ID', 'tipo':'Tipo', 'descricao':'Descricao', 'valor':'Valor', 'data':'Data', 'categoria':'Categoria', 'conta':'Conta', 'status':'Status'}, inplace=True)
    return b, cp, cr, mov

def carregar_clientes():
    df = fetch_df('clientes', ["id", "nome", "telefone", "cpf", "endereco", "historico", "datacadastro"])
    df.rename(columns={'id':'ID', 'nome':'Nome', 'telefone':'Telefone', 'cpf':'CPF', 'endereco':'Endereco', 'historico':'Historico', 'datacadastro':'DataCadastro'}, inplace=True)
    return df

@st.cache_data(ttl=2)
def carregar_estoque_celulares():
    df = fetch_df('estoque', ["id", "modelo", "marca", "cor", "armazenamento", "ram", "imei", "fornecedor", "data_entrada", "custo", "preco_venda", "margem", "status", "cliente_venda", "pagamento_venda"])
    df.rename(columns={'id':'ID', 'modelo':'Modelo', 'marca':'Marca', 'cor':'Cor', 'armazenamento':'Armazenamento', 'ram':'RAM', 'imei':'IMEI', 'fornecedor':'Fornecedor', 'data_entrada':'Data Entrada', 'custo':'Custo', 'preco_venda':'Preço Venda', 'margem':'Margem', 'status':'Status', 'cliente_venda':'Cliente_Venda', 'pagamento_venda':'Pagamento_Venda'}, inplace=True)
    return df

def checar_limite_financeira(cliente, financeira):
    if financeira == "PAYMOBI": return False
    df = carregar_estoque_celulares()
    if not df.empty:
        vendidos = df[df['Status'].astype(str).str.upper().str.contains('VENDIDO', na=False)]
        for _, row in vendidos.iterrows():
            if str(row['Cliente_Venda']).strip().upper() == str(cliente).strip().upper() and financeira.upper() in str(row['Pagamento_Venda']).strip().upper():
                return True
    return False

def calcular_comissao_hoje():
    df = fetch_df('saidas', ['data', 'vendedor', 'comissao_vendedor'])
    if not df.empty:
        hoje_str = hoje.strftime("%Y-%m-%d")
        df['data'] = df['data'].astype(str)
        mask = df['data'].str.startswith(hoje_str) & (df['vendedor'] == st.session_state.usuario_nome)
        return pd.to_numeric(df[mask]['comissao_vendedor'], errors='coerce').sum()
    return 0.0

def carregar_saidas():
    df = fetch_df('saidas', ['id', 'id_estoque', 'modelo', 'imei', 'cliente', 'data', 'valor_venda', 'valor_entrada', 'pagamento', 'obs', 'lucro', 'margem', 'preco_cheio', 'comissao_vendedor', 'vendedor', 'quantidade'])
    df.rename(columns={'id':'ID', 'id_estoque':'ID_Estoque', 'modelo':'Modelo', 'imei':'IMEI', 'cliente':'Cliente', 'data':'Data', 'valor_venda':'Valor_Venda', 'valor_entrada':'Valor_Entrada', 'pagamento':'Pagamento', 'obs':'OBS', 'lucro':'Lucro', 'margem':'Margem', 'preco_cheio':'Preco_Cheio', 'comissao_vendedor':'Comissao_Vendedor', 'vendedor':'Vendedor', 'quantidade':'Quantidade'}, inplace=True)
    return df

# ==========================================
# 2. INJEÇÃO DE CSS GERAL E ESCUDO BLINDADO
# ==========================================
st.markdown("""
<style>
header[data-testid="stHeader"]::after { content: ""; position: absolute; top: 0; right: 0; width: 250px; height: 60px; background-color: transparent !important; z-index: 9999999 !important; pointer-events: auto !important; cursor: default; }
[data-testid="collapsedControl"] { z-index: 99999999 !important; color: var(--text-color) !important; background-color: var(--background-color) !important; border-radius: 50% !important; padding: 2px !important; box-shadow: 0px 2px 5px rgba(0,0,0,0.1) !important; display: flex !important; visibility: visible !important; opacity: 1 !important; }
[data-testid="collapsedControl"] svg { fill: var(--text-color) !important; }
[data-testid="stSidebar"] { background-color: #1c2633 !important; }
[data-testid="stSidebar"] * { color: #e2e8f0 !important; }
[data-testid="stSidebar"] .stButton > button { background-color: transparent !important; border: none !important; color: #e2e8f0 !important; text-align: left !important; justify-content: flex-start !important; padding: 10px 15px !important; box-shadow: none !important; border-radius: 6px !important; transition: all 0.2s ease-in-out !important; }
[data-testid="stSidebar"] .stButton > button:hover { background-color: rgba(255, 255, 255, 0.1) !important; color: #ffffff !important; }
[data-testid="stSidebar"] .stButton > button[kind="primary"] { background-color: rgba(0, 204, 102, 0.15) !important; box-shadow: inset 4px 0px 0px 0px #00cc66 !important; border-radius: 4px 6px 6px 4px !important; color: #00cc66 !important; }
[data-testid="stSidebar"] .stButton > button[kind="primary"] * { color: #00cc66 !important; font-weight: bold !important; }
div[data-testid="column"] > div { background-color: var(--background-color); padding: 25px; border-radius: 10px; border: 1px solid var(--secondary-background-color); box-shadow: 0px 4px 6px rgba(0, 0, 0, 0.05); }
div[data-testid="column"] div[data-testid="column"] > div { background-color: transparent !important; padding: 0px !important; border: none !important; box-shadow: none !important; }
header[data-testid="stHeader"] { background-color: transparent !important; box-shadow: none !important; }
[data-testid="stDecoration"] { display: none !important; }
.block-container { padding-top: 3.5rem !important; }
[data-testid="stImage"] button { display: none !important; }
[data-testid="stNumberInputStepUp"], [data-testid="stNumberInputStepDown"], button[aria-label="Decrement"], button[aria-label="Increment"] { display: none !important; }
input[type=number]::-webkit-inner-spin-button, input[type=number]::-webkit-outer-spin-button { -webkit-appearance: none !important; margin: 0 !important; }
input[type=number] { -moz-appearance: textfield !important; }
.tabela-leve { width: 100%; border-collapse: collapse; font-size: 14px; margin-top: 15px; } .tabela-leve th { background-color: var(--secondary-background-color); text-align: left; padding: 10px; border-bottom: 2px solid #ddd; } .tabela-leve td { padding: 10px; border-bottom: 1px solid #ddd; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# TELA DE LOGIN 
# ==========================================
if not st.session_state.autenticado:
    st.markdown("""<style>[data-testid="stSidebar"] { display: none !important; } header[data-testid="stHeader"] { display: none !important; } .stApp { background-color: #253549 !important; } div[data-testid="column"]:nth-child(2) > div { background-color: #1c2633 !important; border: 1px solid #334458 !important; border-radius: 16px !important; padding: 35px 25px !important; box-shadow: 0px 12px 30px rgba(0, 0, 0, 0.3) !important; }</style>""", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        logo_encontrada = False
        for nome_tentativa in ["logo.png", "logo.jpg", "logo"]:
            caminho_completo = os.path.join(pasta_do_projeto, nome_tentativa)
            if os.path.exists(caminho_completo):
                c_esq, c_cen, c_dir = st.columns([1, 2, 1])
                with c_cen: st.image(caminho_completo, use_column_width=True)
                logo_encontrada = True; break
        if not logo_encontrada: st.markdown("<h1 style='text-align: center; color: #ffffff;'>📱 SUPORTE SMART</h1>", unsafe_allow_html=True)
        st.markdown("<div style='text-align: center; color: #a0aec0; font-size: 15px; margin-bottom: 25px; font-weight: bold;'>ACESSO AO SISTEMA NUVEM</div>", unsafe_allow_html=True)
        with st.form("form_login"):
            usuario_digitado = st.text_input("Usuário", placeholder="Ex: gestor ou vendedor").strip().lower()
            senha_digitada = st.text_input("Senha", type="password", placeholder="Sua senha secreta...")
            if st.form_submit_button("ENTRAR 🔒", use_container_width=True, type="primary"):
                df_usr = fetch_df('usuarios', ['usuario', 'senha', 'nome_completo', 'perfil'])
                user_match = df_usr[(df_usr['usuario'].astype(str).str.lower() == usuario_digitado) & (df_usr['senha'].astype(str) == senha_digitada)]
                if not user_match.empty:
                    st.session_state.autenticado = True; st.session_state.perfil = str(user_match.iloc[0]['perfil']).upper()
                    st.session_state.usuario_nome = str(user_match.iloc[0]['nome_completo']); st.session_state.menu_selecionado = "VENDAS"
                    st.rerun()
                else:
                    if usuario_digitado == "gestor" and senha_digitada == "admin123":
                        st.session_state.autenticado = True; st.session_state.perfil = "GESTOR"; st.session_state.usuario_nome = "Gestor Chefe (Mestre)"; st.session_state.menu_selecionado = "VENDAS"; st.rerun()
                    else: st.error("❌ Usuário ou Senha incorretos.")
        st.stop()

# ==========================================
# MENU LATERAL
# ==========================================
logo_encontrada = False
for nome_tentativa in ["logo.png", "logo.jpg", "logo"]:
    caminho_completo = os.path.join(pasta_do_projeto, nome_tentativa)
    if os.path.exists(caminho_completo):
        encoded_image = get_image_base64(caminho_completo)
        st.sidebar.markdown(f'<div style="display: flex; justify-content: center; width: 100%; padding-bottom: 20px;"><img src="data:image/png;base64,{encoded_image}" style="max-width: 80%; height: auto;"></div>', unsafe_allow_html=True)
        logo_encontrada = True; break
if not logo_encontrada: st.sidebar.markdown("<div style='text-align: center; font-size: 24px; font-weight: bold; margin-bottom: 20px;'>📱 SUPORTE SMART</div>", unsafe_allow_html=True)

st.sidebar.markdown(f"<div style='text-align: center; background-color: rgba(0, 204, 102, 0.1); border: 1px solid #00cc66; color: #00cc66; padding: 5px; border-radius: 5px; font-size: 13px; font-weight: bold; margin-bottom: 20px;'>👤 {st.session_state.usuario_nome}</div>", unsafe_allow_html=True)

if st.session_state.perfil == "VENDEDOR":
    comissao_hoje = calcular_comissao_hoje()
    st.sidebar.markdown(f"<div style='text-align: center; background-color: rgba(255, 153, 0, 0.1); border: 1px solid #ff9900; color: #ff9900; padding: 10px; border-radius: 5px; font-size: 14px; font-weight: bold; margin-bottom: 20px;'>💰 Comissão Hoje<br><span style='font-size: 18px;'>R$ {formata_br(comissao_hoje)}</span></div>", unsafe_allow_html=True)

opcoes = {"CLIENTES": "👤 CLIENTES", "VENDAS": "💰 VENDAS", "ESTOQUE": "📦 ESTOQUE", "PAINEL": "📊 PAINEL FINANCEIRO", "FATURAMENTO": "📄 EXTRATO CAIXA", "CONFIGURACOES": "⚙️ CONFIGURAÇÕES"} if st.session_state.perfil == "GESTOR" else {"CLIENTES": "👤 CLIENTES", "VENDAS": "💰 VENDAS"}

for chave, texto in opcoes.items():
    st.sidebar.button(texto, key=f"btn_{chave}", use_container_width=True, on_click=mudar_aba, args=(chave,), type="primary" if st.session_state.menu_selecionado == chave else "secondary")
        
st.sidebar.markdown("---")
if st.sidebar.button("🚪 SAIR DO SISTEMA", use_container_width=True):
    st.session_state.autenticado = False; st.session_state.menu_selecionado = "VENDAS"; resetar_pdv(); st.rerun()

# --- MÓDULO: CLIENTES (CRM) ---
if st.session_state.menu_selecionado == "CLIENTES":
    st.markdown("<div style='color: #888; font-size: 14px; letter-spacing: 1px; margin-top: -10px; margin-bottom: 20px;'>SUPORTE SMART &nbsp;>&nbsp; <span style='font-weight: bold;'>CRM DE CLIENTES</span></div>", unsafe_allow_html=True)
    aba_cad_cli, aba_list_cli, aba_edit_cli = st.tabs(["➕ Cadastrar Cliente", "📋 Base de Dados", "✏️ Perfil do Cliente"])
    
    with aba_cad_cli:
        with st.form("form_cliente_completo", clear_on_submit=True):
            st.markdown("<div style='font-weight: bold; font-size: 16px; margin-bottom: 15px;'>Dados Pessoais</div>", unsafe_allow_html=True)
            col1, col2, col3 = st.columns(3); nome_cli = col1.text_input("Nome Completo *"); telefone_cli = col2.text_input("Telefone / WhatsApp *"); cpf_cli = col3.text_input("CPF *")
            endereco_cli = st.text_input("Endereço Completo")
            if st.form_submit_button("💾 CADASTRAR CLIENTE", type="primary", use_container_width=True):
                if nome_cli.strip() == "" or telefone_cli.strip() == "" or cpf_cli.strip() == "": st.error("❌ Nome, Telefone e CPF são obrigatórios!")
                else:
                    hist_formatado = f"[{hoje.strftime('%d/%m/%Y')}] Cliente cadastrado no sistema."
                    supabase.table('clientes').insert({"nome": nome_cli.strip().upper(), "telefone": telefone_cli, "cpf": cpf_cli, "endereco": endereco_cli, "historico": hist_formatado, "datacadastro": hoje.strftime("%d/%m/%Y")}).execute()
                    st.success("✅ Cliente cadastrado com sucesso! Já pode prosseguir para a aba de VENDAS."); time.sleep(1.5); st.rerun()
                    
    with aba_list_cli:
        st.markdown("<div style='margin-top:0; margin-bottom: 20px; font-weight: bold; font-size: 16px; text-transform: uppercase;'>📋 Clientes Registrados</div>", unsafe_allow_html=True)
        df_clientes = carregar_clientes()
        # MÁQUINA: Renderiza apenas os 500 mais recentes para evitar lentidão no browser
        if not df_clientes.empty: st.dataframe(df_clientes[['ID', 'Nome', 'Telefone', 'CPF', 'Endereco', 'DataCadastro']].copy().tail(500), use_container_width=True, hide_index=True)
        else: st.info("Nenhum cliente cadastrado ainda.")
            
    with aba_edit_cli:
        st.markdown("<div style='margin-top:0; margin-bottom: 20px; font-weight: bold; font-size: 16px; text-transform: uppercase;'>✏️ Perfil e Atualização</div>", unsafe_allow_html=True)
        if not df_clientes.empty:
            cli_opcoes = {f"{r['ID']} - {r['Nome']} ({r.get('CPF','')})": r['ID'] for _, r in df_clientes.iterrows()}
            id_selecionado = cli_opcoes[st.selectbox("Selecione o Cliente para Visualizar", list(cli_opcoes.keys()))]
            cli_dados = df_clientes[df_clientes['ID'] == id_selecionado].iloc[0]
            
            with st.form("form_edit_cliente"):
                st.markdown("<b>Atualizar Dados Base</b>", unsafe_allow_html=True)
                e_nome = st.text_input("Nome", str(cli_dados['Nome'])); c1, c2 = st.columns(2)
                e_telefone = c1.text_input("Telefone", str(cli_dados.get('Telefone',''))); e_cpf = c2.text_input("CPF", str(cli_dados.get('CPF','')))
                e_end = st.text_input("Endereço", str(cli_dados.get('Endereco', '')))
                st.markdown("<hr><b>Diário do Cliente (Histórico Acumulativo)</b>", unsafe_allow_html=True)
                historico_atual = str(cli_dados.get('Historico', ''))
                novo_historico = st.text_area("Adicionar Nova Observação (Ficará no topo do histórico):")
                st.markdown("<b>Histórico Passado / Registos de Vendas:</b>", unsafe_allow_html=True)
                st.info(historico_atual if historico_atual.strip() and historico_atual != "nan" else "Sem histórico anterior.")
                
                cA, cB = st.columns(2)
                if cA.form_submit_button("💾 SALVAR PERFIL", type="primary", use_container_width=True):
                    hist_final = historico_atual if pd.notna(historico_atual) and historico_atual != "nan" else ""
                    if novo_historico.strip(): hist_final = f"[{hoje.strftime('%d/%m/%Y')}] {novo_historico}\n\n{hist_final}"
                    supabase.table('clientes').update({'nome': e_nome.upper(), 'telefone': e_telefone, 'cpf': e_cpf, 'endereco': e_end, 'historico': hist_final}).eq('id', id_selecionado).execute()
                    st.success("Perfil atualizado!"); time.sleep(1); st.rerun()
                if cB.form_submit_button("❌ EXCLUIR CLIENTE", type="secondary", use_container_width=True):
                    supabase.table('clientes').delete().eq('id', id_selecionado).execute()
                    st.success("Cliente excluído!"); time.sleep(1); st.rerun()
        else: st.info("Nenhum cliente cadastrado no momento.")

# --- MÓDULO: ESTOQUE ---
elif st.session_state.menu_selecionado == "ESTOQUE":
    st.markdown("<div style='color: #888; font-size: 14px; letter-spacing: 1px; margin-top: -10px; margin-bottom: 20px;'>SUPORTE SMART &nbsp;>&nbsp; <span style='font-weight: bold;'>ESTOQUE COMERCIAL</span></div>", unsafe_allow_html=True)
    aba_cad_est, aba_list_est, aba_edit_est, aba_acessorios = st.tabs(["➕ Dar Entrada Celulares", "📋 Tabela Celulares", "✏️ Gerenciar Celulares", "🔌 Estoque de Acessórios"])
    
    with aba_cad_est:
        st.markdown("<div style='margin-top:0; margin-bottom: 20px; font-weight: bold; font-size: 16px; text-transform: uppercase;'>📦 Registro de Compras de Estoque</div>", unsafe_allow_html=True)
        tipo_entrada = st.radio("Tipo de Entrada de Estoque:", ["1. Unitária (Apenas 1 aparelho)", "2. Lote (Vários aparelhos iguais comprados juntos)"], horizontal=True)
        
        with st.form("form_novo_celular"):
            c1, c2, c3 = st.columns(3); m_marca = c1.text_input("Marca (Ex: Apple, Xiaomi)"); m_modelo = c2.text_input("Modelo"); m_cor = c3.text_input("Cor")
            c4, c5, c6 = st.columns(3); m_arm = c4.text_input("Armazenamento (Ex: 128GB)"); m_ram = c5.text_input("Memória RAM (Ex: 4GB)"); m_fornecedor = c6.text_input("Fornecedor")

            st.markdown("<br><b>📱 Detalhes de Preço e IMEI</b>", unsafe_allow_html=True)
            if "1." in tipo_entrada: 
                m_imei_unico = st.text_input("IMEI do Aparelho *"); c7, c8 = st.columns(2)
                m_custo_unit = c7.number_input("Custo Unitário (R$)", min_value=0.0, step=10.0, format="%.2f"); m_preco_unit = c8.number_input("Preço Sugerido (R$)", min_value=0.0, step=10.0, format="%.2f")
                imeis_lista = [m_imei_unico.strip()] if m_imei_unico.strip() else []; custo_total_compra = m_custo_unit
            else: 
                m_imeis_raw = st.text_area("IMEIs dos Aparelhos (Cole todos separando por linha)", height=100); c7, c8 = st.columns(2)
                m_custo_total = c7.number_input("Custo TOTAL Lote (R$)", min_value=0.0, step=10.0, format="%.2f"); m_preco_unit = c8.number_input("Preço Sugerido UNITÁRIO (R$)", min_value=0.0, step=10.0, format="%.2f")
                imeis_lista = [i.strip() for i in m_imeis_raw.replace(",", "\n").split("\n") if i.strip() != ""]; custo_total_compra = m_custo_total
                m_custo_unit = m_custo_total / len(imeis_lista) if len(imeis_lista) > 0 else 0.0

            st.markdown("<hr style='margin: 10px 0;'><div style='font-weight: bold; font-size: 15px; color: #a0aec0; margin-bottom: 10px;'>💸 INTEGRAÇÃO FINANCEIRA (PAGAMENTO DO FORNECEDOR)</div>", unsafe_allow_html=True)
            fin_opcao = st.radio("Como foi/será paga essa compra?", ["1. Não lançar no financeiro (Apenas registrar Estoque)", "2. Já paguei à vista (Tirar do saldo real do Banco/Caixa agora)", "3. Vou pagar depois / Parcelado (Lançar nas Contas a Pagar)"])
            
            c10, c11, c12 = st.columns(3); fin_conta = c10.selectbox("Conta:", ["CAIXA FÍSICO", "CONTA PIX", "BANCO SANTANDER", "BANCO BRADESCO"])
            fin_data = c11.date_input("Data Pagamento:", hoje); fin_parcelas = c12.number_input("Parcelas", min_value=1, max_value=48, value=1, step=1)
            
            if st.form_submit_button("📥 DAR ENTRADA NO(S) APARELHO(S)", type="primary"):
                if m_modelo == "" or len(imeis_lista) == 0: st.error("Modelo e pelo menos um IMEI são obrigatórios!")
                else:
                    margem_unit = (m_preco_unit / m_custo_unit) if m_custo_unit > 0 else 0.0
                    for imei in imeis_lista:
                        supabase.table('estoque').insert({"modelo": m_modelo.upper(), "marca": m_marca.upper(), "cor": m_cor.upper(), "armazenamento": m_arm.upper(), "ram": m_ram.upper(), "imei": imei, "fornecedor": m_fornecedor.upper(), "data_entrada": hoje.strftime("%Y-%m-%d"), "custo": m_custo_unit, "preco_venda": m_preco_unit, "margem": margem_unit, "status": "Em Estoque", "cliente_venda": "", "pagamento_venda": ""}).execute()
                    
                    if "2." in fin_opcao: 
                        supabase.table('movimentacoes').insert({"tipo": "SAIDA", "descricao": f"COMPRA ESTOQUE ({len(imeis_lista)}x {m_marca} {m_modelo})", "valor": custo_total_compra, "data": fin_data.strftime("%d/%m/%Y"), "categoria": "FORNECEDORES", "conta": fin_conta, "status": "REALIZADO"}).execute()
                    elif "3." in fin_opcao: 
                        valor_p = custo_total_compra / fin_parcelas
                        for i in range(fin_parcelas):
                            dp = fin_data + pd.DateOffset(months=i)
                            supabase.table('contas_pagar').insert({"descricao": f"COMPRA ESTOQUE ({len(imeis_lista)}x {m_modelo}) ({i+1}/{fin_parcelas})", "categoria": "FORNECEDORES", "fornecedor": m_fornecedor.upper(), "vencimento": dp.strftime("%d/%m/%Y"), "valor": valor_p, "status": "PENDENTE", "repeticao": f"{i+1}/{fin_parcelas}"}).execute()
                    st.cache_data.clear(); st.success("✅ Cadastrado!"); time.sleep(1.5); st.rerun()

    with aba_list_est:
        st.markdown("<div style='margin-top:0; margin-bottom: 20px; font-weight: bold; font-size: 16px; text-transform: uppercase;'>📋 Gestão Visual de Estoque</div>", unsafe_allow_html=True)
        df_estoque = carregar_estoque_celulares()
        if not df_estoque.empty:
            termo_busca = st.text_input("🔍 Pesquisar Aparelho (Marca, Modelo ou IMEI):", placeholder="Ex: iPhone, Xiaomi, ou 351...").strip().upper()
            df_filtrado = df_estoque.copy()
            if termo_busca:
                mask = (df_filtrado['Marca'].astype(str).str.upper().str.contains(termo_busca) | df_filtrado['Modelo'].astype(str).str.upper().str.contains(termo_busca) | df_filtrado['IMEI'].astype(str).str.upper().str.contains(termo_busca))
                df_filtrado = df_filtrado[mask]
            
            df_disp = df_filtrado[~df_filtrado['Status'].astype(str).str.upper().str.contains('VENDIDO', na=False)]
            df_vendidos = df_filtrado[df_filtrado['Status'].astype(str).str.upper().str.contains('VENDIDO', na=False)].copy()
            
            aba_resumo, aba_detalhe, aba_vendidos, aba_historico = st.tabs(["📦 Resumo Disponíveis", "🔍 Em Estoque (Detalhe / Encalhe)", "🔴 Saídas / Vendidos", "📖 Histórico Geral"])
            with aba_resumo:
                if not df_disp.empty: st.dataframe(df_disp.groupby(['Marca', 'Modelo', 'Armazenamento', 'Cor']).size().reset_index(name='Quantidade em Estoque'), use_container_width=True, hide_index=True)
                else: st.info("Nenhum aparelho disponível encontrado na pesquisa.")
            with aba_detalhe:
                if not df_disp.empty: 
                    df_disp_view = df_disp[['ID', 'Marca', 'Modelo', 'Cor', 'Armazenamento', 'IMEI', 'Data Entrada', 'Custo', 'Preço Venda', 'Status']].copy()
                    df_disp_view['Data Entrada'] = pd.to_datetime(df_disp_view['Data Entrada'], errors='coerce')
                    df_disp_view['Dias Parados'] = (pd.to_datetime(hoje) - df_disp_view['Data Entrada']).dt.days.fillna(0).astype(int)
                    df_disp_view['Data Entrada'] = df_disp_view['Data Entrada'].dt.strftime('%d/%m/%Y')
                    st.markdown("<span style='font-size: 12px; color: #ff4d4d;'>* Valores de 'Dias Parados' acima de 90 ficarão destacados (Alerta de Encalhe).</span>", unsafe_allow_html=True)
                    st.dataframe(df_disp_view.style.map(lambda val: 'color: #ff4d4d' if val > 90 else '', subset=['Dias Parados']), use_container_width=True, hide_index=True)
                else: st.info("Nenhum aparelho em estoque encontrado.")
            with aba_vendidos:
                if not df_vendidos.empty:
                    cols_mostrar = ['Marca', 'Modelo', 'IMEI', 'Status', 'Cliente_Venda', 'Pagamento_Venda']
                    st.dataframe(df_vendidos[cols_mostrar].astype(str).tail(500), use_container_width=True, hide_index=True)
                else: st.info("Nenhuma venda registada até ao momento para esta pesquisa.")
            with aba_historico:
                if not df_filtrado.empty:
                    cols_hist = ['ID', 'Data Entrada', 'Marca', 'Modelo', 'IMEI', 'Status', 'Cliente_Venda', 'Pagamento_Venda']
                    st.dataframe(df_filtrado[cols_hist].astype(str).tail(500), use_container_width=True, hide_index=True)
                else: st.info("Nenhum histórico encontrado.")
        else: st.info("Estoque vazio.")
            
    with aba_edit_est:
        st.markdown("<div style='margin-top:0; margin-bottom: 20px; font-weight: bold; font-size: 16px; text-transform: uppercase;'>✏️ Atualizar ou Excluir Aparelho</div>", unsafe_allow_html=True)
        if not df_estoque.empty:
            est_opcoes = {f"{r['Marca']} {r['Modelo']} - IMEI: {r['IMEI']} ({r.get('Status', 'Em Estoque')})": r['IMEI'] for _, r in df_estoque.iterrows()}
            if est_opcoes:
                imei_sel = est_opcoes[st.selectbox("Selecione um Aparelho para Gerenciar", list(est_opcoes.keys()))]
                dados_ap = df_estoque[df_estoque['IMEI'] == imei_sel].iloc[0]
                
                with st.form("form_edit_estoque"):
                    c1, c2, c3 = st.columns(3); e_marca = c1.text_input("Marca", str(dados_ap.get('Marca', ''))); e_modelo = c2.text_input("Modelo", str(dados_ap.get('Modelo', ''))); e_cor = c3.text_input("Cor", str(dados_ap.get('Cor', '')))
                    c4, c5, c6 = st.columns(3); e_arm = c4.text_input("Armazenamento", str(dados_ap.get('Armazenamento', ''))); e_ram = c5.text_input("Memória RAM", str(dados_ap.get('RAM', ''))); e_imei = c6.text_input("IMEI (Bloqueado p/ segurança)", str(dados_ap.get('IMEI', '')), disabled=True)
                    c7, c8, c9 = st.columns(3); e_forn = c7.text_input("Fornecedor", str(dados_ap.get('Fornecedor', ''))); e_custo = c8.number_input("Custo (R$)", value=float(dados_ap.get('Custo', 0.0)), min_value=0.0, step=1.0); e_preco = c9.number_input("Preço Sugerido (R$)", value=float(dados_ap.get('Preço Venda', 0.0)), min_value=0.0, step=1.0)
                    
                    status_atual = str(dados_ap.get('Status', 'Em Estoque')).upper()
                    e_status = st.selectbox("Status", ["Em Estoque", "VENDIDO"], index=1 if "VENDIDO" in status_atual else 0)
                    
                    colA, colB = st.columns(2)
                    if colA.form_submit_button("💾 SALVAR ALTERAÇÕES", type="primary", use_container_width=True):
                        supabase.table('estoque').update({'modelo': e_modelo, 'marca': e_marca, 'cor': e_cor, 'armazenamento': e_arm, 'ram': e_ram, 'fornecedor': e_forn, 'custo': e_custo, 'preco_venda': e_preco, 'margem': (e_preco/e_custo) if e_custo>0 else 0, 'status': e_status, 'cliente_venda': "" if e_status=="Em Estoque" else dados_ap['Cliente_Venda'], 'pagamento_venda': "" if e_status=="Em Estoque" else dados_ap['Pagamento_Venda']}).eq('imei', str(imei_sel).strip()).execute()
                        st.cache_data.clear(); st.success("Aparelho atualizado!"); time.sleep(2); st.rerun()
                        
                    if colB.form_submit_button("❌ EXCLUIR APARELHO", type="secondary", use_container_width=True):
                        supabase.table('estoque').delete().eq('imei', str(imei_sel).strip()).execute()
                        st.cache_data.clear(); st.success("Aparelho excluído permanente do sistema!"); time.sleep(1.5); st.rerun()

    with aba_acessorios:
        st.markdown("<div style='margin-top:0; margin-bottom: 20px; font-weight: bold; font-size: 16px; text-transform: uppercase;'>🔌 Gestão de Acessórios (PDV)</div>", unsafe_allow_html=True)
        if st.session_state.perfil == "GESTOR":
            with st.form("form_add_acc_estoque", clear_on_submit=True):
                st.markdown("<b>Dar Entrada em Novos Acessórios (Capas, Cabos, Películas)</b>", unsafe_allow_html=True)
                c_a1, c_a2, c_a3, c_a4 = st.columns([2, 1, 1, 1]); nome_a = c_a1.text_input("Nome do Acessório"); custo_a = c_a2.number_input("Custo Unitário (R$)", min_value=0.0, step=1.0, format="%.2f"); preco_a = c_a3.number_input("Preço Sugerido (R$)", min_value=0.0, step=1.0, format="%.2f"); qtd_a = c_a4.number_input("Qtd Comprada", min_value=1, step=1)
                
                if st.form_submit_button("📥 ADICIONAR AO ESTOQUE", type="primary"):
                    if nome_a.strip() == "": st.error("O nome do acessório é obrigatório!")
                    else:
                        ex = supabase.table('acessorios').select("*").ilike('nome_acessorio', nome_a.strip()).execute()
                        if ex.data:
                            qtd_atual = float(ex.data[0]['quantidade'] or 0)
                            supabase.table('acessorios').update({'quantidade': qtd_atual + qtd_a, 'custo': custo_a, 'preco_sugerido': preco_a}).eq('id', ex.data[0]['id']).execute()
                        else: supabase.table('acessorios').insert({'nome_acessorio': nome_a.upper(), 'custo': custo_a, 'preco_sugerido': preco_a, 'quantidade': qtd_a}).execute()
                        st.success(f"✅ {qtd_a}x '{nome_a.upper()}' adicionado(s) ao estoque!"); time.sleep(1.5); st.rerun()
        else: st.info("Apenas o Gestor pode dar entrada em novos acessórios no estoque físico.")
            
        df_acc_bd = fetch_df('acessorios', ['id', 'nome_acessorio', 'custo', 'preco_sugerido', 'quantidade'])
        df_acc_bd.rename(columns={'id':'ID', 'nome_acessorio':'Nome_Acessorio', 'custo':'Custo', 'preco_sugerido':'Preco_Sugerido', 'quantidade':'Quantidade'}, inplace=True)
        if not df_acc_bd.empty:
            st.markdown("<br><b>📦 Estoque Atual de Acessórios</b>", unsafe_allow_html=True)
            df_mostrar_acc = df_acc_bd.copy()
            df_mostrar_acc['Custo'] = df_mostrar_acc['Custo'].apply(lambda x: f"R$ {formata_br(x)}")
            df_mostrar_acc['Preco_Sugerido'] = df_mostrar_acc['Preco_Sugerido'].apply(lambda x: f"R$ {formata_br(x)}")
            st.dataframe(df_mostrar_acc, use_container_width=True, hide_index=True)
        else: st.info("O estoque de acessórios está vazio.")

# --- MÓDULO 1: VENDAS (PDV E CAIXA DIÁRIO) ---
elif st.session_state.menu_selecionado == "VENDAS":
    config = carregar_config()
    st.markdown("<div style='color: #888; font-size: 14px; letter-spacing: 1px; margin-top: -10px; margin-bottom: 20px;'>SUPORTE SMART &nbsp;>&nbsp; <span style='font-weight: bold;'>CENTRAL DE VENDAS E CAIXA</span></div>", unsafe_allow_html=True)

    aba_pdv, aba_caixa_diario = st.tabs(["🛒 PDV (Nova Venda)", "💵 Caixa Diário (Abertura / Fechamento)"])

    with aba_caixa_diario:
        st.markdown("<div style='font-weight: bold; font-size: 18px; text-transform: uppercase; color: #a0aec0; margin-bottom:15px;'>💵 Resumo do Caixa de Hoje</div>", unsafe_allow_html=True)
        
        df_b, df_cp, df_cr, df_mov = carregar_financeiro()
        hoje_str = hoje.strftime("%d/%m/%Y")
        df_hoje = df_mov[df_mov['Data'] == hoje_str].copy() if not df_mov.empty else pd.DataFrame()
        
        if st.session_state.perfil == "GESTOR":
            if not df_hoje.empty:
                df_hoje['Valor'] = pd.to_numeric(df_hoje['Valor'], errors='coerce').fillna(0)
                entradas_hoje = df_hoje[df_hoje['Tipo'] == 'ENTRADA']['Valor'].sum()
                saidas_hoje = df_hoje[df_hoje['Tipo'] == 'SAIDA']['Valor'].sum()
                saldo_hoje = entradas_hoje - saidas_hoje
            else: entradas_hoje = 0.0; saidas_hoje = 0.0; saldo_hoje = 0.0
                
            c1, c2, c3 = st.columns(3)
            with c1: st.markdown(f"""<div style="background-color: var(--background-color); border: 1px solid var(--secondary-background-color); padding: 15px; border-radius: 8px; text-align: center;"><p style="margin:0; font-size: 12px; opacity: 0.7; font-weight: bold;">TOTAL DE ENTRADAS (HOJE)</p><div style="margin:0; color: #00cc66; font-size: 24px; font-weight: bold;">R$ {formata_br(entradas_hoje)}</div></div>""", unsafe_allow_html=True)
            with c2: st.markdown(f"""<div style="background-color: var(--background-color); border: 1px solid var(--secondary-background-color); padding: 15px; border-radius: 8px; text-align: center;"><p style="margin:0; font-size: 12px; opacity: 0.7; font-weight: bold;">SAÍDAS / SANGRIAS (HOJE)</p><div style="margin:0; color: #ff4d4d; font-size: 24px; font-weight: bold;">R$ {formata_br(saidas_hoje)}</div></div>""", unsafe_allow_html=True)
            with c3: st.markdown(f"""<div style="background-color: var(--background-color); border: 1px solid var(--secondary-background-color); padding: 15px; border-radius: 8px; text-align: center;"><p style="margin:0; font-size: 12px; opacity: 0.7; font-weight: bold;">RESULTADO LÍQUIDO DO DIA</p><div style="margin:0; color: #3b82f6; font-size: 24px; font-weight: bold;">R$ {formata_br(saldo_hoje)}</div></div>""", unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
        
        col_sangria, col_lista = st.columns([1, 1.5], gap="large")
        with col_sangria:
            st.markdown("<div style='font-weight: bold; font-size: 16px; margin-bottom: 15px;'>🔄 Abertura, Sangria e Reforço</div>", unsafe_allow_html=True)
            with st.form("form_caixa_diario", clear_on_submit=True):
                tipo_operacao = st.radio("Tipo de Operação:", ["1. Fundo de Caixa / Troco (Entrada)", "2. Despesa Avulsa (Saída)", "3. Transferência p/ Banco (Sangria)"])
                valor_op = st.number_input("Valor (R$)", min_value=0.0, step=10.0, format="%.2f")
                obs_op = st.text_input("Observação / Justificativa:")
                
                if st.form_submit_button("💾 REGISTRAR NO CAIXA", type="primary", use_container_width=True):
                    if valor_op <= 0 or obs_op.strip() == "": st.error("O valor e a observação são obrigatórios!")
                    else:
                        if "1." in tipo_operacao: 
                            supabase.table('movimentacoes').insert({"tipo": "ENTRADA", "descricao": f"FUNDO DE CAIXA: {obs_op}", "valor": valor_op, "data": hoje_str, "categoria": "TROCO", "conta": "CAIXA FÍSICO", "status": "REALIZADO"}).execute()
                        elif "2." in tipo_operacao: 
                            supabase.table('movimentacoes').insert({"tipo": "SAIDA", "descricao": f"DESPESA AVULSA: {obs_op}", "valor": valor_op, "data": hoje_str, "categoria": "OUTROS", "conta": "CAIXA FÍSICO", "status": "REALIZADO"}).execute()
                        elif "3." in tipo_operacao: 
                            supabase.table('movimentacoes').insert({"tipo": "SAIDA", "descricao": f"SANGRIA (SAÍDA CAIXA): {obs_op}", "valor": valor_op, "data": hoje_str, "categoria": "TRANSFERÊNCIA", "conta": "CAIXA FÍSICO", "status": "REALIZADO"}).execute()
                            supabase.table('movimentacoes').insert({"tipo": "ENTRADA", "descricao": f"SANGRIA (DEPÓSITO): {obs_op}", "valor": valor_op, "data": hoje_str, "categoria": "TRANSFERÊNCIA", "conta": "BANCO SANTANDER", "status": "REALIZADO"}).execute()
                        st.cache_data.clear(); st.success("Registado com sucesso!"); time.sleep(1); st.rerun()

        with col_lista:
            if st.session_state.perfil == "GESTOR":
                st.markdown("<div style='font-weight: bold; font-size: 16px; margin-bottom: 15px;'>📋 Movimentações de Hoje</div>", unsafe_allow_html=True)
                if not df_hoje.empty:
                    df_mostrar_hj = df_hoje[['Tipo', 'Descricao', 'Valor', 'Conta', 'Categoria']].copy()
                    df_mostrar_hj['Valor'] = df_mostrar_hj['Valor'].apply(lambda x: f"R$ {formata_br(x)}")
                    st.dataframe(df_mostrar_hj, use_container_width=True, hide_index=True)
                else: st.info("Nenhuma movimentação foi registada no caixa hoje.")
            else: st.info("📌 O histórico detalhado do caixa de hoje é visível apenas para o Gestor. Realize as suas operações ao lado e proceda ao fechamento abaixo no fim do dia.")

            st.markdown("<hr style='margin: 15px 0;'>", unsafe_allow_html=True)
            st.markdown("<div style='font-weight: bold; font-size: 16px; margin-bottom: 5px; color: #ff9900;'>🔒 FECHAMENTO DE CAIXA</div>", unsafe_allow_html=True)
            st.markdown("<div style='background-color: #ff4d4d20; padding:10px; border-radius:5px; margin-bottom: 10px; font-size: 13px;'><b style='color:#ff4d4d;'>🚨 ALERTA:</b> Se retirou dinheiro para o cofre, FAÇA A SANGRIA (Transferência) primeiro! Se não fizer, o sistema vai cobrar esse dinheiro na contagem.</div>", unsafe_allow_html=True)
            
            if not df_mov.empty: df_mov['Valor'] = pd.to_numeric(df_mov['Valor'], errors='coerce').fillna(0)
            if not df_hoje.empty: df_hoje['Valor'] = pd.to_numeric(df_hoje['Valor'], errors='coerce').fillna(0)
            
            ent_gaveta = df_mov[df_mov['Conta'].isin(['CAIXA FÍSICO', 'PIX / DINHEIRO']) & (df_mov['Tipo'] == 'ENTRADA')]['Valor'].sum() if not df_mov.empty else 0.0
            sai_gaveta = df_mov[df_mov['Conta'].isin(['CAIXA FÍSICO', 'PIX / DINHEIRO']) & (df_mov['Tipo'] == 'SAIDA')]['Valor'].sum() if not df_mov.empty else 0.0
            saldo_inicial_gaveta = df_b[df_b['Nome'] == 'CAIXA FÍSICO']['Saldo_Inicial'].sum() if not df_b.empty else 0.0
            saldo_esperado_dinheiro = saldo_inicial_gaveta + ent_gaveta - sai_gaveta

            ent_cartao = df_hoje[df_hoje['Conta'].isin(['DÉBITO', 'CRÉDITO À VISTA', 'CRÉDITO PARCELADO (LOJA PAGA JUROS)', 'CRÉDITO PARCELADO (CLIENTE PAGA JUROS)']) & (df_hoje['Tipo'] == 'ENTRADA')]['Valor'].sum() if not df_hoje.empty else 0.0
            saldo_esperado_cartao = ent_cartao

            if st.session_state.caixa_travado:
                st.error("🚨 DIVERGÊNCIA DE VALORES DETETADA! O CAIXA FOI TRAVADO POR SEGURANÇA.")
                st.info("O valor contado fisicamente não corresponde à matemática do sistema. Apenas o Gestor pode intervir.")
                with st.form("form_destravar"):
                    senha_gestor = st.text_input("🔑 Senha de Administrador (Gestor):", type="password")
                    if st.form_submit_button("🔓 DESBLOQUEAR CAIXA", type="primary", use_container_width=True):
                        if senha_gestor == "admin123":
                            st.session_state.caixa_travado = False
                            st.success("Caixa desbloqueado! Refaça a contagem do zero ou insira os lançamentos que faltam.")
                            time.sleep(2); st.rerun()
                        else: st.error("Senha incorreta! Bloqueio mantido.")
            else:
                if st.session_state.perfil == "GESTOR":
                    st.info(f"O sistema calcula que devem existir **R$ {formata_br(saldo_esperado_dinheiro)}** na Gaveta (Dinheiro/Pix) e **R$ {formata_br(saldo_esperado_cartao)}** faturados nas Maquininhas (Cartões).")
                else:
                    st.markdown("<div style='font-size: 14px; margin-bottom: 10px; color: #888;'><b>FECHAMENTO CEGO:</b> Separe as notas de dinheiro/Pix e os comprovantes da maquininha de cartão. Digite os totais exatos abaixo.</div>", unsafe_allow_html=True)
                
                with st.form("form_fechar_caixa", clear_on_submit=True):
                    val_din = float(saldo_esperado_dinheiro) if st.session_state.perfil == "GESTOR" else 0.0
                    val_cart = float(saldo_esperado_cartao) if st.session_state.perfil == "GESTOR" else 0.0
                    valor_real_dinheiro = st.number_input("Valor físico contado na Gaveta (Dinheiro / Pix) R$:", min_value=0.0, step=10.0, format="%.2f", value=val_din)
                    valor_real_cartao = st.number_input("Total dos comprovantes das Maquininhas (Cartões) R$:", min_value=0.0, step=10.0, format="%.2f", value=val_cart)
                    
                    if st.form_submit_button("🔒 CONFERIR E FECHAR O DIA", type="primary", use_container_width=True):
                        diff_dinheiro = valor_real_dinheiro - saldo_esperado_dinheiro
                        diff_cartao = valor_real_cartao - saldo_esperado_cartao
                        if abs(diff_dinheiro) > 0.01 or abs(diff_cartao) > 0.01:
                            st.session_state.caixa_travado = True; st.rerun()
                        else:
                            supabase.table('movimentacoes').insert({"tipo": "INFO", "descricao": "🔒 FECHAMENTO DE CAIXA DO DIA", "valor": 0.0, "data": hoje_str, "categoria": "FECHAMENTO", "conta": "CAIXA FÍSICO", "status": "REALIZADO"}).execute()
                            st.cache_data.clear(); st.success("Caixa fechado com sucesso! Os valores bateram perfeitamente."); time.sleep(2); st.rerun()

    with aba_pdv:
        if st.session_state.recibo is not None:
            r = st.session_state.recibo
            st.markdown("<div style='text-align:center; color:#00cc66; font-size: 24px; font-weight: bold; margin-bottom: 10px;'>✅ Venda Concluída com Sucesso!</div>", unsafe_allow_html=True)
            nf_aviso = "<p class='center' style='font-size: 11px; margin-top: 15px;'>* Nota Fiscal solicitada e será enviada eletronicamente.</p>" if r['nf'] else ""
            itens_html = "".join([f"<p style='font-size: 12px; margin:2px 0;'>{i['qtd']}x {i['nome']} - R$ {formata_br(i['preco'])}</p>" for i in r['itens']])
            
            html_financiamento = ""
            if r.get('forma_pagto_base') == "BOLETO PARCELADO":
                html_financiamento = f"""<p style="font-size: 12px; margin: 2px 0;"><b>VALOR FINANCIADO:</b> R$ {formata_br(r.get('valor_financiado', 0))}</p><p style="font-size: 12px; margin: 2px 0;"><b>PAGO NA ENTRADA/LOJA:</b> R$ {formata_br(r.get('valor_entrada', 0))}</p>"""
            html_taxa = f"""<p class="center" style="font-size: 11px; margin-top: 8px; color: #333;">(Taxa Maquininha: {r.get('taxa_pct', 0):.2f}% | R$ {formata_br(r.get('taxa_valor', 0))})</p>""" if r.get('taxa_pct', 0) > 0 else ""

            html_cupom = f"""
            <html><head><style>
                body {{ font-family: 'Courier New', monospace; background-color: transparent; color: black; padding: 15px; margin: 0; display: flex; flex-direction: column; align-items: center; }}
                .cupom {{ width: 350px; background-color: #ffffff; border: 1px solid #ccc; padding: 20px; box-shadow: 0px 4px 10px rgba(0,0,0,0.2); }}
                hr {{ border: 0; border-top: 1px dashed black; margin: 10px 0; }}
                .center {{ text-align: center; }} p, h3 {{ margin: 5px 0; }}
                @media print {{ body {{ background-color: white; }} .cupom {{ box-shadow: none; border: none; width: 100%; }} .no-print {{ display: none; }} }}
            </style></head><body>
                <div class="cupom">
                    <div class="center"><h3 style="margin-bottom: 0;">SUPORTE SMART</h3><p style="font-size: 11px; margin-top: 2px;">Soluções em Tecnologia</p></div><hr>
                    <p style="font-size: 12px; text-align: right;">{r['data']}</p><hr>
                    <p style="font-size: 12px;"><b>CLIENTE:</b> {r['cliente']}</p><hr>
                    <p class="center" style="font-size: 14px;"><b>CUPOM NÃO FISCAL</b></p>
                    {itens_html}
                    <hr>
                    <p style="font-size: 12px; margin: 2px 0;"><b>SUBTOTAL:</b> R$ {formata_br(r['valor_unit'])}</p>
                    <p style="font-size: 12px; margin: 2px 0;"><b>DESCONTO/AJUSTE:</b> R$ {formata_br(r.get('desconto_dinheiro', 0))}</p>
                    <hr>
                    <h3 style="font-size: 16px; margin: 5px 0;">TOTAL GERAL: R$ {formata_br(r['total'])}</h3>
                    <p style="font-size: 12px; margin: 2px 0;"><b>PAGAMENTO:</b> {r['pagamento']}</p>
                    {html_financiamento}
                    {html_taxa}
                    <hr>
                    <p style="font-size: 12px; margin: 2px 0; text-align: center; color: #333;"><b>GARANTIA ({r.get('dias_garantia', 90)} dias):</b> Válida até {r.get('data_garantia', 'N/A')}</p>
                    <hr>
                    <p class="center" style="font-size: 12px; margin-top: 15px;">Obrigado pela preferência!</p>{nf_aviso}<br>
                    <div class="center no-print"><button onclick="window.print()" style="padding: 12px 25px; font-size: 16px; cursor: pointer; background-color: #00cc66; color: white; border: none; border-radius: 5px; font-weight: bold; width: 100%;">🖨️ IMPRIMIR PDF / A4</button></div>
                </div>
            </body></html>"""
            components.html(html_cupom, height=600)
            
            col1, col2, col3 = st.columns([1, 1, 1])
            if col1.button("🖨️ IMPRESSÃO TÉRMICA DIRETA", use_container_width=True):
                texto_venda = f"""========================================\n             SUPORTE SMART              \n         Solucoes em Tecnologia         \n========================================\nData: {r['data']}\nCliente: {r['cliente'][:30]}\n----------------------------------------\n            CUPOM NAO FISCAL            \n----------------------------------------\n"""
                for i in r['itens']: texto_venda += f"{str(i['qtd']).zfill(2)}x {str(i['nome'])[:22].ljust(22)} R${formata_br(i['preco']).rjust(10)}\n"
                texto_venda += f"""----------------------------------------\nSUBTOTAL:                 R$ {formata_br(r['valor_unit']).rjust(10)}\nDESCONTO:                 R$ {formata_br(r.get('desconto_dinheiro',0)).rjust(10)}\nTOTAL GERAL:              R$ {formata_br(r['total']).rjust(10)}\nPAGAMENTO: {r['pagamento'][:28]}\n----------------------------------------\nGARANTIA ({r.get('dias_garantia', 90)} dias): Ate {r.get('data_garantia','N/A')}\n----------------------------------------\n       Obrigado pela preferencia!       \n========================================\n\n\n\n\n\n\n\n"""
                caminho_recibo_txt = os.path.join(pasta_do_projeto, "recibo_temp.txt")
                try:
                    with open(caminho_recibo_txt, "w", encoding="utf-8") as f: f.write(texto_venda)
                    os.startfile(caminho_recibo_txt, "print"); st.success("Enviado silenciosamente para a Impressora Padrão do Windows!")
                except Exception as e: st.error(f"Erro de conexão com o Windows: {e}. Verifique a impressora padrão.")
            
            if col2.button("🔄 INICIAR NOVA VENDA", use_container_width=True, type="primary"): mudar_aba("VENDAS"); resetar_pdv(); st.rerun()

        else:
            df_clientes = carregar_clientes(); lista_clientes = df_clientes['Nome'].tolist() if not df_clientes.empty else []
            df_estoque = carregar_estoque_celulares(); dict_aparelhos = {}; lista_aparelhos = []
            if not df_estoque.empty:
                df_disp = df_estoque[~df_estoque['Status'].astype(str).str.upper().str.contains('VENDIDO', na=False)]
                for _, row in df_disp.iterrows():
                    label = f"{row['Marca']} {row['Modelo']} {row['Armazenamento']} - {row['Cor']} (IMEI: {row['IMEI']})"
                    lista_aparelhos.append(label); dict_aparelhos[label] = row

            col_esq, col_dir = st.columns([1.2, 1], gap="large")
            with col_esq:
                # MÁQUINA: Reorganização inteligente - Selecionar o Aparelho primeiro e Pagamento depois
                c_tit, c_limpar = st.columns([3, 1])
                c_tit.markdown("<div style='font-weight: bold; font-size: 18px; text-transform: uppercase; color: #a0aec0;'>👤 1. Cliente e Aparelho</div>", unsafe_allow_html=True)
                if c_limpar.button("🧹 Limpar Venda", use_container_width=True): resetar_pdv(); st.rerun()
                
                if len(lista_clientes) == 0: st.warning("⚠️ Nenhum cliente cadastrado no sistema. Vá à aba 'CLIENTES'.")
                cliente_selecionado = st.selectbox("👤 SELECIONE O CLIENTE", lista_clientes if len(lista_clientes) > 0 else ["Nenhum cliente cadastrado"])

                aparelho_sel = st.selectbox("📱 SELECIONE O APARELHO", ["Nenhum (Só Acessórios)"] + lista_aparelhos)
                if aparelho_sel != "Nenhum (Só Acessórios)":
                    dados_prod = dict_aparelhos[aparelho_sel]
                    preco_sugerido = float(dados_prod['Preço Venda'])
                    custo_sugerido = float(dados_prod['Custo'])
                    
                    if st.session_state.perfil == "GESTOR":
                        c_ap1, c_ap2 = st.columns(2)
                        preco_venda_aparelho = c_ap1.number_input("Preço de Venda do Aparelho (R$)", value=preco_sugerido, min_value=0.0, step=1.0, format="%.2f")
                        custo_aparelho = c_ap2.number_input("Custo do Aparelho (R$)", value=custo_sugerido, min_value=0.0, step=1.0, format="%.2f")
                    else:
                        preco_venda_aparelho = st.number_input("Preço de Venda do Aparelho (R$)", value=preco_sugerido, min_value=0.0, step=1.0, format="%.2f")
                        custo_aparelho = custo_sugerido 
                else: preco_venda_aparelho = 0.0; custo_aparelho = 0.0
                tem_celular = aparelho_sel != "Nenhum (Só Acessórios)"

                st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)
                st.markdown("<div style='font-weight: bold; font-size: 18px; text-transform: uppercase; color: #a0aec0;'>💳 2. Configuração do Pagamento</div>", unsafe_allow_html=True)
                
                forma_pagto = st.selectbox("💳 FORMA DE PAGAMENTO PRINCIPAL", ["BOLETO PARCELADO", "PIX / DINHEIRO", "DÉBITO", "CRÉDITO À VISTA", "CRÉDITO PARCELADO (LOJA PAGA JUROS)", "CRÉDITO PARCELADO (CLIENTE PAGA JUROS)"], key="forma_pagto_sel")

                financeira = ""; taxa_mercado = 0.0; desconto_pct = 0.0; taxa_entrada = 0.0; parcela_entrada = 1; tipo_pgto_entrada = ""
                entrada_financeira = 0.0; entrada_cliente_aparelho = 0.0; parcelas_fin = 1; recorrencia_paymobi = "MENSAL"
                total_aces = sum(i['subtotal'] for i in st.session_state.acessorios)

                if forma_pagto == "BOLETO PARCELADO":
                    c_fin1, c_fin2 = st.columns(2)
                    financeira = c_fin1.selectbox("FINANCEIRA", ["AIVA", "PAYJOY", "PAYMOBI"], key="fin_sel")
                    taxa_mercado = 10.0 if financeira == "AIVA" else (2.0 if financeira == "PAYJOY" else 0.0)
                    
                    if financeira != "PAYMOBI": c_fin2.number_input("MDR DA FINANCEIRA (%)", value=taxa_mercado, disabled=True, format="%.2f")

                    if financeira == "PAYMOBI":
                        st.warning("💡 **ESTRATÉGIA PAYMOBI:**\nO sistema exige que a **Entrada Mínima** seja 100% do **Custo** do aparelho + R$ 50,00.", icon="💡")
                        c_pm1, c_pm2 = st.columns(2)
                        parcelas_fin = c_pm1.number_input("Quantas Parcelas (Paymobi)?", min_value=1, max_value=36, value=2, step=1, key="parc_fin")
                        recorrencia_paymobi = c_pm2.selectbox("Recorrência:", ["MENSAL", "QUINZENAL"], key="rec_paymobi")
                        
                        min_entrada_paymobi = custo_aparelho + 50.0 if tem_celular else 0.0
                        entrada_financeira = 0.0 
                        entrada_cliente_aparelho = st.number_input("ENTRADA DO APARELHO QUE O CLIENTE VAI DAR (R$)", min_value=min_entrada_paymobi, value=max(min_entrada_paymobi, 0.0), step=10.0, format="%.2f", key="val_ent_cli")
                    else:
                        c_fin3, c_fin4 = st.columns(2)
                        entrada_financeira = c_fin3.number_input("ENTRADA DO APARELHO PEDIDA P/ FINANCEIRA (R$)", min_value=0.0, step=10.0, format="%.2f", key="val_ent_fin")
                        entrada_cliente_aparelho = c_fin4.number_input("ENTRADA DO APARELHO QUE CLIENTE TEM (R$)", min_value=0.0, step=10.0, format="%.2f", key="val_ent_cli")

                    total_pago_hora = entrada_cliente_aparelho + total_aces
                    st.markdown(f"<div style='font-size: 15px; font-weight: bold; margin-bottom: 10px; color: #00cc66;'>💰 TOTAL A PAGAR NA HORA: R$ {formata_br(total_pago_hora)} <span style='font-size: 12px; color: #888;'>(Entrada R$ {formata_br(entrada_cliente_aparelho)} + Acessórios R$ {formata_br(total_aces)})</span></div>", unsafe_allow_html=True)
                    st.markdown("<div style='font-size: 14px; font-weight: bold; margin-top: 10px;'>Como esse valor de Entrada/Acessórios será pago?</div>", unsafe_allow_html=True)
                    tipo_pgto_entrada = st.selectbox("FORMA DE PAGAMENTO DA ENTRADA", ["PIX / DINHEIRO", "DÉBITO", "CRÉDITO À VISTA", "CRÉDITO PARCELADO (LOJA PAGA JUROS)", "CRÉDITO PARCELADO (CLIENTE PAGA JUROS)"], key="tipo_pgto_ent_sel")
                    
                    if tipo_pgto_entrada == "DÉBITO": taxa_entrada = 1.39
                    elif tipo_pgto_entrada == "CRÉDITO À VISTA": taxa_entrada = 3.49
                    elif tipo_pgto_entrada == "CRÉDITO PARCELADO (CLIENTE PAGA JUROS)": taxa_entrada = 3.49
                    elif tipo_pgto_entrada == "CRÉDITO PARCELADO (LOJA PAGA JUROS)":
                        parcela_entrada = st.number_input("Qtd. Parcelas da Entrada", min_value=2, max_value=18, value=2, step=1, key="parc_ent_val")
                        if 2 <= parcela_entrada <= 6: taxa_entrada = 2.79 + (1.29 * parcela_entrada)
                        elif 7 <= parcela_entrada <= 12: taxa_entrada = 3.09 + (1.29 * parcela_entrada)
                        elif 13 <= parcela_entrada <= 18: taxa_entrada = 3.59 + (1.29 * parcela_entrada)

                    if taxa_entrada > 0:
                        taxa_valor_ent = total_pago_hora * (taxa_entrada / 100.0)
                        liq_ent = total_pago_hora - taxa_valor_ent
                        st.markdown(f"<div style='font-size: 13px; color: #ff4d4d; margin-top:-5px; margin-bottom:10px;'>➖ <b>Taxa Maquininha ({taxa_entrada:.2f}%):</b> Desconta R$ {formata_br(taxa_valor_ent)} da entrada. Líquido na Loja: <b>R$ {formata_br(liq_ent)}</b></div>", unsafe_allow_html=True)
                
                else:
                    c5, c6 = st.columns(2)
                    desconto_pct = c5.number_input("DESCONTO NA VENDA (%)", value=0.0, min_value=0.0, max_value=20.0, step=1.0, format="%.2f", key="desc_pct")
                    if forma_pagto == "DÉBITO": taxa_mercado = 1.39
                    elif forma_pagto == "CRÉDITO À VISTA": taxa_mercado = 3.49
                    elif forma_pagto == "CRÉDITO PARCELADO (CLIENTE PAGA JUROS)": taxa_mercado = 3.49
                    elif forma_pagto == "CRÉDITO PARCELADO (LOJA PAGA JUROS)":
                        parcelas = c6.number_input("Qtd. Parcelas", min_value=2, max_value=18, value=2, step=1, key="qtd_parc")
                        if 2 <= parcelas <= 6: taxa_mercado = 2.79 + (1.29 * parcelas)
                        elif 7 <= parcelas <= 12: taxa_mercado = 3.09 + (1.29 * parcelas)
                        elif 13 <= parcelas <= 18: taxa_mercado = 3.59 + (1.29 * parcelas)
                    if forma_pagto not in ["PIX / DINHEIRO", "CRÉDITO PARCELADO (LOJA PAGA JUROS)"]: c6.number_input("TAXA MAQUININHA (%)", value=taxa_mercado, disabled=True, format="%.2f")
                    elif forma_pagto == "PIX / DINHEIRO": c6.number_input("TAXA MAQUININHA (%)", value=0.0, disabled=True, format="%.2f")

                st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)
                st.markdown("<div style='font-weight: bold; font-size: 18px; text-transform: uppercase; color: #a0aec0;'>🔌 3. Acessórios Extras</div>", unsafe_allow_html=True)
                
                df_acc_bd = fetch_df('acessorios', ['id', 'nome_acessorio', 'custo', 'preco_sugerido', 'quantidade'])
                df_acc_bd.rename(columns={'id':'ID', 'nome_acessorio':'Nome_Acessorio', 'custo':'Custo', 'preco_sugerido':'Preco_Sugerido', 'quantidade':'Quantidade'}, inplace=True)
                df_acc_bd['Quantidade'] = pd.to_numeric(df_acc_bd['Quantidade'], errors='coerce').fillna(0)
                pecas_disp = df_acc_bd[df_acc_bd['Quantidade'] > 0]

                if not pecas_disp.empty:
                    opcoes_acc = {f"{r['Nome_Acessorio']} (Estoque: {int(r['Quantidade'])} | Sugerido: R$ {formata_br(r['Preco_Sugerido'])})": r for _, r in pecas_disp.iterrows()}
                    lista_nomes_acc = ["Selecione..."] + list(opcoes_acc.keys())
                else:
                    opcoes_acc = {}
                    lista_nomes_acc = ["Nenhum acessório em estoque"]
                    
                with st.form("form_add_acc", clear_on_submit=True):
                    acc_sel = st.selectbox("Acessório do Estoque Oficial:", lista_nomes_acc)
                    c_acc1, c_acc3 = st.columns([3, 1])
                    preco_acc_personalizado = c_acc1.number_input("Preço de Venda Unit. (R$) - Digite 0 para usar o Sugerido", min_value=0.0, step=1.0, format="%.2f")
                    qtd_acc = c_acc3.number_input("Quantidade", value=1, min_value=1, step=1)
                    
                    if st.form_submit_button("➕ ADICIONAR ACESSÓRIO", use_container_width=True):
                        if acc_sel == "Selecione..." or acc_sel == "Nenhum acessório em estoque":
                            st.error("Selecione um acessório válido.")
                        else:
                            dados_acc = opcoes_acc[acc_sel]
                            preco_final = preco_acc_personalizado if preco_acc_personalizado > 0 else float(dados_acc['Preco_Sugerido'])
                            custo_real = float(dados_acc['Custo'])
                            
                            found = False
                            for item in st.session_state.acessorios:
                                if str(item['db_id']) == str(dados_acc['ID']):
                                    if item['qtd'] + qtd_acc > float(dados_acc['Quantidade']): st.error("Estoque insuficiente!")
                                    else:
                                        item['qtd'] += qtd_acc; item['subtotal'] += preco_final * qtd_acc; item['subcusto'] += custo_real * qtd_acc
                                    found = True; break
                            if not found:
                                if qtd_acc > float(dados_acc['Quantidade']): st.error("Estoque insuficiente!")
                                else: st.session_state.acessorios.append({"tipo": "ACESSORIO", "nome": str(dados_acc['Nome_Acessorio']), "imei": "-", "id_estoque": f"ACC_{dados_acc['ID']}", "preco": preco_final, "custo": custo_real, "qtd": qtd_acc, "subtotal": preco_final * qtd_acc, "subcusto": custo_real * qtd_acc, "db_id": str(dados_acc['ID'])})
                            st.rerun()

                if st.session_state.acessorios:
                    for idx, item in enumerate(st.session_state.acessorios):
                        st.markdown(f"<div style='background-color: var(--secondary-background-color); padding: 8px 12px; border-radius: 5px; margin-bottom: 5px; font-size: 14px; display:flex; justify-content:space-between;'><span><b>{item['qtd']}x</b> {item['nome']}</span><span style='color:#00cc66; font-weight:bold;'>R$ {formata_br(item['subtotal'])}</span></div>", unsafe_allow_html=True)
                    if st.button("🗑️ Limpar Acessórios", type="secondary"): st.session_state.acessorios = []; st.rerun()

                st.markdown("<br>", unsafe_allow_html=True)
                gerar_nf = st.checkbox("📄 Solicitar Emissão de Nota Fiscal (NFe)")

            with col_dir:
                if not tem_celular and not st.session_state.acessorios:
                    st.markdown("""<div style="background-color: var(--background-color); border: 1px dashed var(--secondary-background-color); border-radius: 10px; padding: 40px 25px; text-align: center; opacity: 0.5;"><h3 style="margin:0;">🛒 Venda Vazia</h3><p style="font-size: 14px;">Selecione o aparelho ou adicione acessórios.</p></div>""", unsafe_allow_html=True)
                else:
                    total_acessorios_venda = sum(a['subtotal'] for a in st.session_state.acessorios)
                    total_acessorios_custo = sum(a['subcusto'] for a in st.session_state.acessorios)
                    total_produtos = preco_venda_aparelho + total_acessorios_venda
                    custo_total_produtos = custo_aparelho + total_acessorios_custo

                    if forma_pagto == "BOLETO PARCELADO":
                        if financeira == "PAYMOBI": valor_financiado = preco_venda_aparelho - entrada_cliente_aparelho
                        else: valor_financiado = preco_venda_aparelho - entrada_financeira
                        if valor_financiado < 0: valor_financiado = 0.0 
                        total_pago_hora = entrada_cliente_aparelho + total_acessorios_venda
                        receita_bruta = valor_financiado + total_pago_hora
                        comissao_fin = valor_financiado * (taxa_mercado / 100.0); comissao_ent = total_pago_hora * (taxa_entrada / 100.0); comissao = comissao_fin + comissao_ent
                        desconto_dinheiro = total_produtos - receita_bruta
                    else:
                        desconto_dinheiro = total_produtos * (desconto_pct / 100.0); receita_bruta = total_produtos - desconto_dinheiro
                        comissao = receita_bruta * (taxa_mercado / 100.0); valor_financiado = 0.0; total_pago_hora = receita_bruta

                    lucro_bruto = receita_bruta - custo_total_produtos
                    impostos = (receita_bruta * 0.06) + 5.00
                    markup_atual = ((receita_bruta - custo_total_produtos) / custo_total_produtos * 100) if custo_total_produtos > 0 else 100.0
                    
                    limite_premium = float(config.get("limite_custo_premium", 900.0))
                    is_premium = custo_aparelho > limite_premium
                    comissao_vendedor_total = 0.0; faixa_comissao = ""
                    
                    if tem_celular:
                        if is_premium:
                            if markup_atual >= 100.0: comissao_vendedor_total = 50.0; faixa_comissao = "Premium (Margem >= 100%)"
                            elif markup_atual >= 90.0: comissao_vendedor_total = 30.0; faixa_comissao = "Premium (Margem >= 90%)"
                            else: comissao_vendedor_total = 10.0; faixa_comissao = "Premium (Margem < 90%)"
                        else:
                            if markup_atual >= 110.0: comissao_vendedor_total = 50.0; faixa_comissao = "Padrão (Margem >= 110%)"
                            elif markup_atual >= 100.0: comissao_vendedor_total = 30.0; faixa_comissao = "Padrão (Margem >= 100%)"
                            else: comissao_vendedor_total = 10.0; faixa_comissao = "Padrão (Margem < 100%)"
                    else:
                        com_acc_pct = float(config.get("comissao_acessorio_pct", 5.0))
                        comissao_vendedor_total = receita_bruta * (com_acc_pct / 100.0); faixa_comissao = "Apenas Acessórios"

                    lucro_liquido = lucro_bruto - comissao - impostos - comissao_vendedor_total
                    margem_liquida = (lucro_liquido / receita_bruta * 100) if receita_bruta > 0 else 0.0

                    st.markdown("<div style='margin-top:0; margin-bottom: 20px; font-weight: bold; font-size: 18px; text-transform: uppercase;'>📊 Simulação da Venda</div>", unsafe_allow_html=True)
                    if forma_pagto == "BOLETO PARCELADO":
                        texto_parcelas = ""
                        if financeira == "PAYMOBI":
                            val_parcela = valor_financiado / parcelas_fin if parcelas_fin > 0 else 0.0
                            texto_parcelas = f"<p style='margin:10px 0 0 0; font-size:16px; color:#ff9900;'><b>💰 {parcelas_fin}x de R$ {formata_br(val_parcela)} ({recorrencia_paymobi})</b></p>"
                        st.markdown(f"""<div style="background-color: var(--background-color); border: 1px solid var(--secondary-background-color); border-radius: 10px; padding: 20px; text-align: center;"><p style="margin:0; font-size: 14px; opacity: 0.7; font-weight: bold;">Receita Real (Financiado + Pago na Hora)</p><div style="margin:10px 0; color: #00cc66; font-size: 38px; font-weight: bold;">R$ {formata_br(receita_bruta)}</div><p style="margin:0; font-size: 13px; opacity: 0.8;">Financiado: R$ {formata_br(valor_financiado)} &nbsp;|&nbsp; Pago na Hora: R$ {formata_br(total_pago_hora)}</p>{texto_parcelas}</div>""", unsafe_allow_html=True)
                    else:
                        st.markdown(f"""<div style="background-color: var(--background-color); border: 1px solid var(--secondary-background-color); border-radius: 10px; padding: 20px; text-align: center;"><p style="margin:0; font-size: 16px; opacity: 0.7; font-weight: bold;">Total a Cobrar do Cliente</p><div style="margin:10px 0; color: #00cc66; font-size: 38px; font-weight: bold;">R$ {formata_br(receita_bruta)}</div><p style="margin:0; opacity: 0.7;">Pagamento: {forma_pagto}</p></div>""", unsafe_allow_html=True)
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.session_state.perfil == "GESTOR":
                        st.markdown("<div style='font-weight: bold; font-size: 14px; margin-bottom: 10px; color:#888;'>DRE PROJETADA DA VENDA TOTAL</div>", unsafe_allow_html=True)
                        st.markdown(f"""<div style="font-size: 14px; background-color: var(--secondary-background-color); padding: 15px; border-radius: 8px;"><div style="display:flex; justify-content:space-between; padding-bottom:6px;"><span>Soma dos Produtos</span><span>R$ {formata_br(total_produtos)}</span></div><div style="display:flex; justify-content:space-between; padding-bottom:6px;"><span>Desconto / Ajuste Boleto</span><span style="color:#ff4d4d;">- R$ {formata_br(desconto_dinheiro)}</span></div><div style="display:flex; justify-content:space-between; padding-bottom:6px; border-bottom:1px solid #ddd; margin-bottom:6px;"><b>RECEITA BRUTA FINAL</b><b style="color:#00cc66;">R$ {formata_br(receita_bruta)}</b></div><div style="display:flex; justify-content:space-between; padding-bottom:6px;">Custo Total<span style="color:#ff4d4d;">- R$ {formata_br(custo_total_produtos)}</span></div><div style="display:flex; justify-content:space-between; padding-bottom:6px;">Taxas (Maquininha/Fin.)<span style="color:#ff4d4d;">- R$ {formata_br(comissao)}</span></div><div style="display:flex; justify-content:space-between; padding-bottom:6px;">Comissão Vendedor<span style="color:#ff4d4d;">- R$ {formata_br(comissao_vendedor_total)}</span></div><div style="display:flex; justify-content:space-between; padding-bottom:6px; border-bottom:1px solid #ddd; margin-bottom:6px;">Impostos e Despesas Fixas<span style="color:#ff4d4d;">- R$ {formata_br(impostos)}</span></div><div style="display:flex; justify-content:space-between;"><b>LUCRO LÍQUIDO (Bolsos)</b><b style="color:#00cc66; font-size:16px;">R$ {formata_br(lucro_liquido)}</b></div><div style="display:flex; gap:10px; margin-top:15px;"><div style="flex:1; border:1px solid #ddd; padding:8px; text-align:center; border-radius:5px;"><div style="font-size:10px; opacity:0.8;">MARGEM (MARKUP)</div><b>{formata_br(markup_atual)}%</b></div><div style="flex:1; border:1px solid #00cc66; background-color:rgba(0,204,102,0.1); padding:8px; text-align:center; border-radius:5px;"><div style="font-size:10px; color:#00cc66;">LUCRO LÍQUIDO</div><b style=\"color:#00cc66;\">{formata_br(margem_liquida)}%</b></div></div></div>""", unsafe_allow_html=True)
                    else:
                        if comissao_vendedor_total < 50.0 and tem_celular: st.markdown(f"<div style='font-size: 13px; color: #ff9900; margin-top:10px; text-align:center; border: 1px dashed #ff9900; padding:10px; border-radius:5px;'>🔥 <b>ESTRATÉGIA DE VENDAS:</b> Sua comissão está em R$ {formata_br(comissao_vendedor_total)}. Adicione acessórios ou negocie uma entrada maior para bater a meta máxima de R$ 50!</div>", unsafe_allow_html=True)
                        elif tem_celular: st.markdown(f"<div style='font-size: 13px; color: #00cc66; margin-top:10px; text-align:center; border: 1px solid #00cc66; padding:10px; border-radius:5px; background-color: rgba(0, 204, 102, 0.1);'>🏆 <b>PARABÉNS!</b> Você atingiu a margem para a comissão MÁXIMA!</div>", unsafe_allow_html=True)
                        else: st.info(f"🏆 Sua comissão projetada: **R$ {formata_br(comissao_vendedor_total)}**")
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    precisa_liberacao = False; senha_gerente = ""
                    
                    if st.session_state.perfil == "VENDEDOR":
                        alvo_minimo = float(config.get("margem_celular_pct", 100.0)) if tem_celular else float(config.get("margem_acessorio_pct", 100.0))
                        if markup_atual < alvo_minimo:
                            st.warning("⚠️ A margem de lucro está abaixo do mínimo aceitável pela loja. Tente aumentar o preço de venda para liberar o sistema e ainda aumentar o ganho da sua comissão! Caso contrário, essa venda só irá ser liberada com autorização do Gestor.")
                            senha_gerente = st.text_input("🔑 Senha do Gestor", type="password")
                            precisa_liberacao = True

                    if st.button("🚀 CONCLUIR VENDA", use_container_width=True, type="primary"):
                        if st.session_state.usuario_nome is None or str(st.session_state.usuario_nome).strip() == "": st.error("❌ ERRO CRÍTICO: Nome do vendedor não encontrado na memória. Faça logout e login novamente para registar a comissão.")
                        elif len(lista_clientes) == 0 or cliente_selecionado == "Nenhum cliente cadastrado": st.error("❌ É obrigatório cadastrar o cliente na aba 'CLIENTES' antes de vender.")
                        elif precisa_liberacao and senha_gerente != "admin123": st.error("❌ Senha do Gestor incorreta! Venda não autorizada.")
                        elif forma_pagto == "BOLETO PARCELADO" and financeira == "PAYMOBI" and tem_celular and (round(entrada_cliente_aparelho, 2) < round(custo_aparelho + 50.0, 2)):
                            if st.session_state.perfil == "GESTOR": st.error(f"❌ VENDA BLOQUEADA (PAYMOBI): A entrada do cliente (R$ {formata_br(entrada_cliente_aparelho)}) deve ser no mínimo igual ao custo do aparelho + R$ 50 (Mínimo: R$ {formata_br(custo_aparelho + 50.0)}).")
                            else: st.error(f"❌ VENDA BLOQUEADA (PAYMOBI): A entrada do cliente não atinge o valor mínimo de segurança exigido pela loja (Custo + R$ 50).")
                        elif forma_pagto == "BOLETO PARCELADO" and tem_celular and checar_limite_financeira(cliente_selecionado, financeira): st.error(f"❌ VENDA BLOQUEADA: O cliente '{cliente_selecionado}' já possui um limite ativo na {financeira}.")
                        else:
                            try:
                                itens_venda = []
                                if tem_celular: itens_venda.append({"tipo": "CELULAR", "nome": f"{row_ap['Marca']} {row_ap['Modelo']} ({row_ap['IMEI']})", "imei": row_ap['IMEI'], "id_estoque": row_ap['ID'], "preco": preco_venda_aparelho, "custo": custo_aparelho, "qtd": 1, "subtotal": preco_venda_aparelho, "subcusto": custo_aparelho})
                                itens_venda.extend(st.session_state.acessorios)
                                nomes_produtos = []
                                
                                res_sai = supabase.table('saidas').select("id").order("id", desc=True).limit(1).execute()
                                n_id_s = int(res_sai.data[0]['id']) + 1 if res_sai.data else 1

                                for item in itens_venda:
                                    nomes_produtos.append(item['nome'])
                                    if item['tipo'] == 'CELULAR':
                                        status_venda_est = f"{forma_pagto} ({financeira})" if forma_pagto == "BOLETO PARCELADO" else forma_pagto
                                        supabase.table('estoque').update({'status': 'VENDIDO', 'cliente_venda': cliente_selecionado, 'pagamento_venda': status_venda_est}).eq('imei', item['imei']).execute()
                                    
                                    prop = item['subtotal'] / total_produtos if total_produtos > 0 else 0
                                    supabase.table('saidas').insert({'id': n_id_s, 'id_estoque': str(item['id_estoque']), 'modelo': item['nome'], 'imei': item.get('imei', '-'), 'cliente': cliente_selecionado, 'data': hoje.strftime("%Y-%m-%d %H:%M"), 'valor_venda': receita_bruta * prop, 'valor_entrada': receita_bruta * prop, 'pagamento': f"{forma_pagto} ({financeira}) + {tipo_pgto_entrada}" if forma_pagto == "BOLETO PARCELADO" else forma_pagto, 'lucro': lucro_bruto * prop, 'margem': markup_atual, 'comissao_vendedor': comissao_vendedor_total * prop, 'vendedor': st.session_state.usuario_nome, 'quantidade': item.get('qtd', 1)}).execute()
                                    n_id_s += 1
                                    
                                    if item['tipo'] == 'ACESSORIO':
                                        q_bd = float(supabase.table('acessorios').select('quantidade').eq('id', item['db_id']).execute().data[0]['quantidade'])
                                        supabase.table('acessorios').update({'quantidade': max(0, q_bd - item['qtd'])}).eq('id', item['db_id']).execute()

                                resumo_nomes = ", ".join(nomes_produtos)[:80] + ("..." if len(", ".join(nomes_produtos)) > 80 else "")
                                
                                if total_pago_hora > 0:
                                    conta_origem = tipo_pgto_entrada if forma_pagto == "BOLETO PARCELADO" else forma_pagto
                                    supabase.table('movimentacoes').insert({'tipo': 'ENTRADA', 'descricao': f"VENDA PDV: {cliente_selecionado} - {resumo_nomes}", 'valor': total_pago_hora, 'data': hoje.strftime("%d/%m/%Y"), 'categoria': 'VENDA DE CELULAR' if tem_celular else 'VENDA DE ACESSÓRIOS', 'conta': conta_origem, 'status': 'REALIZADO'}).execute()
                                
                                if valor_financiado > 0 and forma_pagto == "BOLETO PARCELADO":
                                    if financeira in ["PAYJOY", "AIVA"]:
                                        dias_prazo = 7 if financeira == "PAYJOY" else 2; data_prev = adicionar_dias_uteis(hoje, dias_prazo)
                                        supabase.table('contas_receber').insert({'origem_cliente': financeira, 'descricao': f"BOLETO {financeira}: {cliente_selecionado} - {resumo_nomes}", 'vencimento': data_prev.strftime("%d/%m/%Y"), 'valor': valor_financiado, 'data_pagamento': "", 'status': 'PENDENTE', 'conta_destino': 'BANCO SANTANDER'}).execute()
                                    elif financeira == "PAYMOBI":
                                        valor_parcela = valor_financiado / parcelas_fin if parcelas_fin > 0 else 0
                                        for i in range(parcelas_fin):
                                            if recorrencia_paymobi == "QUINZENAL": data_prev = hoje + pd.Timedelta(days=15 * (i+1))
                                            else: data_prev = hoje + pd.DateOffset(months=i+1)
                                            supabase.table('contas_receber').insert({'origem_cliente': financeira, 'descricao': f"BOLETO {financeira} {i+1}/{parcelas_fin}: {cliente_selecionado} - {resumo_nomes}", 'vencimento': data_prev.strftime("%d/%m/%Y"), 'valor': valor_parcela, 'data_pagamento': "", 'status': 'PENDENTE', 'conta_destino': 'CAIXA FÍSICO'}).execute()

                                dias_garantia = int(config.get("dias_garantia", 90))
                                data_garantia_venda = (hoje + datetime.timedelta(days=dias_garantia)).strftime("%d/%m/%Y")

                                hist_venda = f"[{hoje.strftime('%d/%m/%Y')}] Venda Concluída ({len(itens_venda)} itens) via {forma_pagto}. Receita Bruta Loja: R$ {formata_br(receita_bruta)}. Garantia válida até: {data_garantia_venda}."
                                df_cli = fetch_df('clientes', ['id', 'nome', 'historico'])
                                idx = df_cli[df_cli['nome'] == cliente_selecionado].index
                                if not idx.empty:
                                    hist_atual = df_cli.at[idx[0], 'historico']
                                    hist_final = f"{hist_venda}\n\n{hist_atual if pd.notna(hist_atual) and str(hist_atual) != 'nan' else ''}"
                                    supabase.table('clientes').update({'historico': hist_final}).eq('id', int(df_cli.at[idx[0], 'id'])).execute()

                                st.cache_data.clear()
                                pagto_label = f"{forma_pagto} - {financeira} ({parcelas_fin}x)" if forma_pagto == "BOLETO PARCELADO" and financeira == "PAYMOBI" else (f"{forma_pagto} - {financeira}" if forma_pagto == "BOLETO PARCELADO" else forma_pagto)
                                st.session_state.recibo = {"data": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"), "cliente": cliente_selecionado, "produto": "Múltiplos Itens (Ver Recibo)", "itens": itens_venda, "valor_unit": total_produtos, "desconto_dinheiro": desconto_dinheiro, "total": receita_bruta, "pagamento": pagto_label, "nf": gerar_nf, "forma_pagto_base": forma_pagto, "valor_financiado": valor_financiado if forma_pagto == "BOLETO PARCELADO" else 0.0, "valor_entrada": total_pago_hora if forma_pagto == "BOLETO PARCELADO" else receita_bruta, "taxa_pct": taxa_entrada if forma_pagto == "BOLETO PARCELADO" else taxa_mercado, "taxa_valor": comissao_ent if forma_pagto == "BOLETO PARCELADO" else comissao, "dias_garantia": dias_garantia, "data_garantia": data_garantia_venda}
                                resetar_pdv(); st.rerun()
                            except Exception as e: st.error(f"Erro ao salvar na nuvem. Detalhe: {e}")

# --- MÓDULO 2: NOVO PAINEL FINANCEIRO ---
elif st.session_state.menu_selecionado == "PAINEL":
    st.markdown("<div style='color: #888; font-size: 14px; letter-spacing: 1px; margin-top: -10px; margin-bottom: 20px;'>SUPORTE SMART &nbsp;>&nbsp; <span style='font-weight: bold;'>ERP FINANCEIRO (NUVEM)</span></div>", unsafe_allow_html=True)
    df_b, df_cp, df_cr, df_mov = carregar_financeiro(); hoje_dt = pd.to_datetime(hoje)
    
    if not df_cp.empty: df_cp['Venc_DT'] = pd.to_datetime(df_cp['Vencimento'], format='%d/%m/%Y', errors='coerce'); df_cp['Valor'] = pd.to_numeric(df_cp['Valor'], errors='coerce').fillna(0)
    if not df_cr.empty: df_cr['Venc_DT'] = pd.to_datetime(df_cr['Vencimento'], format='%d/%m/%Y', errors='coerce'); df_cr['Valor'] = pd.to_numeric(df_cr['Valor'], errors='coerce').fillna(0)
    if not df_mov.empty: df_mov['Valor'] = pd.to_numeric(df_mov['Valor'], errors='coerce').fillna(0)
    
    saldo_inicial_bancos = df_b['Saldo_Inicial'].sum() if not df_b.empty else 0
    entradas_reais = df_mov[(df_mov['Tipo'] == 'ENTRADA') & (df_mov['Status'] == 'REALIZADO')]['Valor'].sum() if not df_mov.empty else 0
    saidas_reais = df_mov[(df_mov['Tipo'] == 'SAIDA') & (df_mov['Status'] == 'REALIZADO')]['Valor'].sum() if not df_mov.empty else 0
    saldo_real_hoje = saldo_inicial_bancos + entradas_reais - saidas_reais

    contas_vencidas = df_cp[(df_cp['Status'] == 'PENDENTE') & (df_cp['Venc_DT'] < hoje_dt)]['Valor'].sum() if not df_cp.empty else 0
    recebimentos_atrasados = df_cr[(df_cr['Status'] == 'PENDENTE') & (df_cr['Venc_DT'] < hoje_dt)]['Valor'].sum() if not df_cr.empty else 0

    aba_dash, aba_pendentes, aba_lancamentos, aba_relatorios, aba_comissoes, aba_simulador, aba_bancos = st.tabs(["📊 Visão Geral", "✅ Baixas e Exclusões", "💸 Lançamentos", "📈 Relatórios / DRE", "🏆 Comissões", "🔮 Simulador", "🏦 Saldos Iniciais"])
    
    with aba_dash:
        st.markdown("<div style='font-size: 20px; font-weight: bold; margin-bottom: 15px; color: #a0aec0;'>VISÃO DE CAIXA E PROJEÇÃO</div>", unsafe_allow_html=True)
        dias_projecao = st.radio("Período da Projeção:", [7, 30, 90, 365], format_func=lambda x: f"Próximos {x} dias" if x < 365 else "Próximos 12 meses", horizontal=True)
        limite_proj = hoje_dt + pd.Timedelta(days=dias_projecao)
        
        a_receber_periodo = df_cr[(df_cr['Status'] == 'PENDENTE') & (df_cr['Venc_DT'] >= hoje_dt) & (df_cr['Venc_DT'] <= limite_proj)]['Valor'].sum() if not df_cr.empty else 0
        a_pagar_periodo = df_cp[(df_cp['Status'] == 'PENDENTE') & (df_cp['Venc_DT'] >= hoje_dt) & (df_cp['Venc_DT'] <= limite_proj)]['Valor'].sum() if not df_cp.empty else 0
        saldo_projetado_periodo = saldo_real_hoje + a_receber_periodo - a_pagar_periodo

        c1, c2, c3, c4 = st.columns(4)
        with c1: st.markdown(f"""<div style="background-color: var(--background-color); border: 1px solid var(--secondary-background-color); padding: 20px 10px; border-radius: 10px; text-align: center;"><p style="margin:0; font-size: 12px; opacity: 0.7; font-weight: bold;">SALDO REAL NA CONTA</p><div style="margin:0; color: #00cc66; font-size: 24px; font-weight: bold;">R$ {formata_br(saldo_real_hoje)}</div></div>""", unsafe_allow_html=True)
        with c2: st.markdown(f"""<div style="background-color: var(--background-color); border: 1px solid var(--secondary-background-color); padding: 20px 10px; border-radius: 10px; text-align: center;"><p style="margin:0; font-size: 12px; opacity: 0.7; font-weight: bold;">A RECEBER (PERÍODO)</p><div style="margin:0; color: #3b82f6; font-size: 24px; font-weight: bold;">R$ {formata_br(a_receber_periodo)}</div></div>""", unsafe_allow_html=True)
        with c3: st.markdown(f"""<div style="background-color: var(--background-color); border: 1px solid var(--secondary-background-color); padding: 20px 10px; border-radius: 10px; text-align: center;"><p style="margin:0; font-size: 12px; opacity: 0.7; font-weight: bold;">A PAGAR (PERÍODO)</p><div style="margin:0; color: #ff4d4d; font-size: 24px; font-weight: bold;">R$ {formata_br(a_pagar_periodo)}</div></div>""", unsafe_allow_html=True)
        with c4:
            cor_saldo = "#00cc66" if saldo_projetado_periodo >= 0 else "#ff4d4d"
            st.markdown(f"""<div style="background-color: var(--background-color); border: 1px solid var(--secondary-background-color); padding: 20px 10px; border-radius: 10px; text-align: center;"><p style="margin:0; font-size: 12px; opacity: 0.7; font-weight: bold;">SALDO PROJETADO FINAL</p><div style="margin:0; color: {cor_saldo}; font-size: 24px; font-weight: bold;">R$ {formata_br(saldo_projetado_periodo)}</div></div>""", unsafe_allow_html=True)
        
        st.markdown("<br><hr style='margin: 10px 0;'><br>", unsafe_allow_html=True)
        st.markdown("<div style='font-size: 16px; font-weight: bold; margin-bottom: 10px; text-align: center;'>📅 CALENDÁRIO FINANCEIRO (Entradas e Saídas)</div>", unsafe_allow_html=True)
        
        if 'cal_mes' not in st.session_state: st.session_state.cal_mes = hoje_dt.month; st.session_state.cal_ano = hoje_dt.year
            
        c_m1, c_m2, c_m3 = st.columns([1, 2, 1])
        meses_pt = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
        
        with c_m2:
            col_mes, col_ano = st.columns(2)
            novo_mes_nome = col_mes.selectbox("Pesquisar Mês:", meses_pt, index=st.session_state.cal_mes - 1)
            novo_ano = col_ano.number_input("Pesquisar Ano:", min_value=2020, max_value=2100, value=st.session_state.cal_ano, step=1)
            if meses_pt.index(novo_mes_nome) + 1 != st.session_state.cal_mes or novo_ano != st.session_state.cal_ano:
                st.session_state.cal_mes = meses_pt.index(novo_mes_nome) + 1; st.session_state.cal_ano = novo_ano; st.rerun()

        cp_pend = df_cp[df_cp['Status'].astype(str).str.upper() == 'PENDENTE'].copy() if not df_cp.empty else pd.DataFrame()
        cr_pend = df_cr[df_cr['Status'].astype(str).str.upper() == 'PENDENTE'].copy() if not df_cr.empty else pd.DataFrame()
        cp_agg = {}; cr_agg = {}
        if not cp_pend.empty: cp_agg = cp_pend.groupby(cp_pend['Venc_DT'].dt.date)['Valor'].sum().to_dict()
        if not cr_pend.empty: cr_agg = cr_pend.groupby(cr_pend['Venc_DT'].dt.date)['Valor'].sum().to_dict()
            
        cal_html = "<table style='width:100%; border-collapse: collapse; table-layout: fixed; margin-bottom: 20px; font-size: 12px;'><tr style='background-color: var(--secondary-background-color); text-align:center;'><th style='padding:5px;'>Seg</th><th style='padding:5px;'>Ter</th><th style='padding:5px;'>Qua</th><th style='padding:5px;'>Qui</th><th style='padding:5px;'>Sex</th><th style='padding:5px;'>Sáb</th><th style='padding:5px;'>Dom</th></tr>"
        semanas = calendar.monthcalendar(st.session_state.cal_ano, st.session_state.cal_mes)
        
        st.markdown("""<div style='display:flex; justify-content:center; gap: 20px; margin-bottom: 10px; font-size: 12px; font-weight: bold;'><div><span style='color:#ff4d4d;'>🔴</span> Atrasado</div><div><span style='color:#ff9900;'>🟡</span> Vence Hoje</div><div><span style='color:#00cc66;'>🟢</span> A Receber (Futuro)</div><div><span style='color:#a855f7;'>🟣</span> A Pagar (Futuro)</div></div>""", unsafe_allow_html=True)
        
        for semana in semanas:
            cal_html += "<tr>"
            for dia in semana:
                if dia == 0: cal_html += "<td style='border: 1px solid var(--secondary-background-color); background-color: rgba(255,255,255,0.02); height: 70px;'></td>"
                else:
                    data_dia = datetime.date(st.session_state.cal_ano, st.session_state.cal_mes, dia)
                    val_rec = cr_agg.get(data_dia, 0.0); val_pag = cp_agg.get(data_dia, 0.0)
                    bg_color = "transparent"; border_style = "1px solid var(--secondary-background-color)"
                    if data_dia == hoje_dt.date(): bg_color = "rgba(255, 153, 0, 0.05)"; border_style = "2px solid #ff9900"
                        
                    cal_html += f"<td style='padding: 4px; border: {border_style}; vertical-align: top; background-color: {bg_color}; height: 70px; width: 14%;'>"
                    cor_dia = "#ff9900" if data_dia == hoje_dt.date() else "var(--text-color)"
                    peso_dia = "bold" if data_dia == hoje_dt.date() else "normal"
                    cal_html += f"<div style='font-weight:{peso_dia}; font-size:13px; text-align:right; margin-bottom:2px; color:{cor_dia};'>{dia}</div>"
                    
                    if val_rec > 0:
                        cor_r = "#ff4d4d" if data_dia < hoje_dt.date() else ("#ff9900" if data_dia == hoje_dt.date() else "#00cc66")
                        icone_r = "🔴" if data_dia < hoje_dt.date() else ("🟡" if data_dia == hoje_dt.date() else "🟢")
                        cal_html += f"<div style='background-color: {cor_r}15; border-left: 3px solid {cor_r}; color: {cor_r}; font-size: 10px; padding: 2px 4px; margin-bottom: 2px; line-height: 1.2; border-radius: 0 4px 4px 0;'><b>{icone_r} REC:</b><br>R$ {formata_br(val_rec)}</div>"
                        
                    if val_pag > 0:
                        cor_p = "#ff4d4d" if data_dia < hoje_dt.date() else ("#ff9900" if data_dia == hoje_dt.date() else "#a855f7")
                        icone_p = "🔴" if data_dia < hoje_dt.date() else ("🟡" if data_dia == hoje_dt.date() else "🟣")
                        cal_html += f"<div style='background-color: {cor_p}15; border-left: 3px solid {cor_p}; color: {cor_p}; font-size: 10px; padding: 2px 4px; margin-bottom: 2px; line-height: 1.2; border-radius: 0 4px 4px 0;'><b>{icone_p} PAG:</b><br>R$ {formata_br(val_pag)}</div>"
                    cal_html += "</td>"
            cal_html += "</tr>"
        cal_html += "</table>"
        
        st.markdown(cal_html, unsafe_allow_html=True)
        st.markdown("<br><hr style='margin: 10px 0;'><br>", unsafe_allow_html=True)

        dias_projetados = []; saldo_acumulado = saldo_real_hoje; alertas_negativos = []
        for i in range(1, dias_projecao + 1):
            dia = hoje_dt + pd.Timedelta(days=i)
            cr_dia = df_cr[(df_cr['Status'] == 'PENDENTE') & (df_cr['Venc_DT'] == dia)]['Valor'].sum() if not df_cr.empty else 0
            cp_dia = df_cp[(df_cp['Status'] == 'PENDENTE') & (df_cp['Venc_DT'] == dia)]['Valor'].sum() if not df_cp.empty else 0
            saldo_dia = cr_dia - cp_dia; saldo_acumulado += saldo_dia
            if cr_dia > 0 or cp_dia > 0: dias_projetados.append({"Data": dia.strftime("%d/%m/%Y"), "Entradas Prev.": f"R$ {formata_br(cr_dia)}", "Saídas Prev.": f"R$ {formata_br(cp_dia)}", "Saldo Projetado": f"R$ {formata_br(saldo_acumulado)}"})
            if saldo_acumulado < 0: alertas_negativos.append(f"{dia.strftime('%d/%m/%Y')} — Saldo projetado: -R$ {formata_br(abs(saldo_acumulado))}")

        col_alertas, col_proj = st.columns([1, 1.5], gap="large")
        with col_alertas:
            st.markdown("<div style='font-size: 16px; font-weight: bold; margin-bottom: 15px;'>⚠️ ALERTAS DE RISCO</div>", unsafe_allow_html=True)
            if alertas_negativos:
                for alerta in alertas_negativos[:4]: st.markdown(f"<div style='background-color: rgba(255, 77, 77, 0.1); border-left: 4px solid #ff4d4d; padding: 10px; margin-bottom: 10px; font-size: 14px; color: #ff4d4d;'><b>🔴 Risco de Caixa Negativo:</b><br>{alerta}</div>", unsafe_allow_html=True)
            else: st.markdown("<div style='background-color: rgba(0, 204, 102, 0.1); border-left: 4px solid #00cc66; padding: 10px; margin-bottom: 10px; font-size: 14px; color: #00cc66;'>✅ Fluxo Saudável para o período selecionado.</div>", unsafe_allow_html=True)
            
            if contas_vencidas > 0: st.markdown(f"<div style='background-color: rgba(255, 153, 0, 0.1); border-left: 4px solid #ff9900; padding: 10px; margin-bottom: 10px; font-size: 14px; color: #ff9900;'>🟡 <b>Atenção:</b> R$ {formata_br(contas_vencidas)} em Contas a Pagar Vencidas.</div>", unsafe_allow_html=True)
            if recebimentos_atrasados > 0: st.markdown(f"<div style='background-color: rgba(255, 153, 0, 0.1); border-left: 4px solid #ff9900; padding: 10px; margin-bottom: 10px; font-size: 14px; color: #ff9900;'>🟡 <b>Atenção:</b> R$ {formata_br(recebimentos_atrasados)} em Boletos Atrasados.</div>", unsafe_allow_html=True)

        with col_proj:
            st.markdown("<div style='font-size: 16px; font-weight: bold; margin-bottom: 15px;'>📅 PROJEÇÃO DIÁRIA (LISTA DETALHADA)</div>", unsafe_allow_html=True)
            if dias_projetados: st.dataframe(pd.DataFrame(dias_projetados).head(50), use_container_width=True, hide_index=True)
            else: st.info("Nenhuma movimentação futura agendada.")

    with aba_relatorios:
        st.markdown("<div style='font-weight: bold; font-size: 16px; text-transform: uppercase;'>📈 O Raio-X da Loja (DRE e Inadimplência)</div>", unsafe_allow_html=True)
        col_dre, col_inad = st.columns([1.2, 1], gap="large")
        with col_dre:
            st.markdown("<div style='color: #00cc66; font-weight: bold; margin-bottom: 10px;'>📊 DRE DO CAIXA</div>", unsafe_allow_html=True)
            if not df_mov.empty:
                df_mov['Data_DT'] = pd.to_datetime(df_mov['Data'], format='%d/%m/%Y', errors='coerce')
                df_mov['Mês/Ano'] = df_mov['Data_DT'].dt.strftime('%m/%Y')
                meses_disponiveis = sorted(df_mov['Mês/Ano'].dropna().unique().tolist(), reverse=True)
                
                if meses_disponiveis:
                    mes_dre_sel = st.selectbox("📅 Selecione o Mês de Referência para a DRE:", meses_disponiveis)
                    df_mes = df_mov[(df_mov['Mês/Ano'] == mes_dre_sel) & (df_mov['Status'] == 'REALIZADO')].copy()
                    df_dre = df_mes[~df_mes['Categoria'].astype(str).str.upper().isin(['TROCO', 'TRANSFERÊNCIA', 'ESTORNO'])]
                    
                    receitas_mes = df_dre[df_dre['Tipo'] == 'ENTRADA']['Valor'].sum()
                    despesas_mes = df_dre[df_dre['Tipo'] == 'SAIDA']['Valor'].sum()
                    lucro_mes = receitas_mes - despesas_mes
                    cor_lucro = "#00cc66" if lucro_mes >= 0 else "#ff4d4d"
                    
                    st.markdown(f"""<div style="font-size: 14px; background-color: var(--secondary-background-color); padding: 15px; border-radius: 8px;"><div style="display:flex; justify-content:space-between; padding-bottom:6px; border-bottom:1px solid #ddd; margin-bottom:6px;"><b>RECEITA TOTAL (ENTRADAS)</b><b style="color:#00cc66;">R$ {formata_br(receitas_mes)}</b></div><div style="display:flex; justify-content:space-between; padding-bottom:6px;">Custos e Despesas (Saídas)<span style="color:#ff4d4d;">- R$ {formata_br(despesas_mes)}</span></div><div style="display:flex; justify-content:space-between; padding-top:10px; border-top:1px solid #ddd; margin-top:6px;"><b>LUCRO LÍQUIDO DO MÊS</b><b style="color:{cor_lucro}; font-size:18px;">R$ {formata_br(lucro_mes)}</b></div></div>""", unsafe_allow_html=True)
                    st.markdown("<br><b>Top 5 Categorias de Gastos</b>", unsafe_allow_html=True)
                    df_saidas_mes = df_dre[df_dre['Tipo'] == 'SAIDA']
                    if not df_saidas_mes.empty:
                        gastos_cat = df_saidas_mes.groupby('Categoria')['Valor'].sum().sort_values(ascending=False).head(5)
                        st.bar_chart(gastos_cat)
                    else: st.info("Sem despesas registradas neste mês.")
                else: st.info("Nenhuma movimentação realizada ainda.")
            else: st.info("Extrato vazio. Realize vendas ou lançamentos para gerar a DRE.")
        
        with col_inad:
            st.markdown("<div style='color: #ff4d4d; font-weight: bold; margin-bottom: 10px;'>🚨 RADAR DE INADIMPLÊNCIA (BOLETOS ATRASADOS)</div>", unsafe_allow_html=True)
            if not df_cr.empty:
                df_atrasados = df_cr[(df_cr['Status'].str.upper() == 'PENDENTE') & (df_cr['Venc_DT'] < hoje_dt)].copy()
                if not df_atrasados.empty:
                    df_atrasados['Dias_Atraso'] = (hoje_dt - df_atrasados['Venc_DT']).dt.days
                    total_rua = df_atrasados['Valor'].sum()
                    st.markdown(f"""<div style="background-color: rgba(255, 77, 77, 0.1); border: 1px solid #ff4d4d; padding: 15px; border-radius: 8px; text-align: center; margin-bottom: 15px;"><p style="margin:0; font-size: 13px; color: #ff4d4d; font-weight: bold;">DINHEIRO DA LOJA NA RUA (ATRASADO)</p><div style="margin:0; color: #ff4d4d; font-size: 28px; font-weight: bold;">R$ {formata_br(total_rua)}</div></div>""", unsafe_allow_html=True)
                    df_mostrar_inad = df_atrasados[['Descricao', 'Vencimento', 'Valor', 'Dias_Atraso']].sort_values(by='Dias_Atraso', ascending=False)
                    df_mostrar_inad['Valor'] = df_mostrar_inad['Valor'].apply(lambda x: f"R$ {formata_br(x)}")
                    df_mostrar_inad.rename(columns={'Descricao': 'Cliente / Origem', 'Dias_Atraso': 'Atraso (Dias)'}, inplace=True)
                    st.dataframe(df_mostrar_inad, use_container_width=True, hide_index=True)
                else: st.markdown("<div style='background-color: rgba(0, 204, 102, 0.1); border-left: 4px solid #00cc66; padding: 15px; border-radius: 8px; color: #00cc66;'><b>🎉 Parabéns!</b> Nenhum cliente ou financeira está com pagamentos atrasados neste momento.</div>", unsafe_allow_html=True)
            else: st.info("Nenhuma conta a receber registrada.")

    with aba_comissoes:
        st.markdown("<div style='font-weight: bold; font-size: 16px; text-transform: uppercase;'>🏆 Relatório Flexível de Comissões</div>", unsafe_allow_html=True)
        try:
            df_saidas = carregar_saidas()
            if not df_saidas.empty:
                if 'Vendedor' not in df_saidas.columns: df_saidas['Vendedor'] = "VENDEDOR ANTIGO"
                df_saidas['Data_DT'] = pd.to_datetime(df_saidas['Data'], errors='coerce')
                df_saidas['Comissao_Vendedor'] = pd.to_numeric(df_saidas['Comissao_Vendedor'], errors='coerce').fillna(0.0)

                c_filtro1, c_filtro2 = st.columns(2)
                vendedores_banco = []
                try:
                    df_u = fetch_df('usuarios', ['nome_completo', 'perfil'])
                    vendedores_banco = df_u[df_u['perfil'] == 'VENDEDOR']['nome_completo'].tolist()
                except: pass
                
                vendedores_vendas = df_saidas['Vendedor'].dropna().unique().tolist()
                lista_vendedores = ["TODOS"] + sorted(list(set(vendedores_banco + [str(v) for v in vendedores_vendas if str(v).strip() != ""])))
                vendedor_sel = c_filtro1.selectbox("👤 Filtrar por Vendedor:", lista_vendedores)
                st.markdown("<div style='font-size: 11px; color: #888; margin-top: -15px; margin-bottom: 10px;'>💡 <b>Dica de Calendário:</b> Clique na data de <b>Início</b> e depois clique na data de <b>Fim</b>.</div>", unsafe_allow_html=True)
                periodo_sel = c_filtro2.date_input("📅 Selecione o Período (Início e Fim):", [hoje.replace(day=1), hoje])
                
                if len(periodo_sel) == 2:
                    data_inicio, data_fim = periodo_sel; data_inicio = pd.to_datetime(data_inicio); data_fim = pd.to_datetime(data_fim)
                    mask = (df_saidas['Data_DT'].dt.date >= data_inicio.date()) & (df_saidas['Data_DT'].dt.date <= data_fim.date())
                    df_filtrado = df_saidas[mask].copy()
                    if vendedor_sel != "TODOS": df_filtrado = df_filtrado[df_filtrado['Vendedor'].astype(str) == vendedor_sel]
                    total_comissao = df_filtrado['Comissao_Vendedor'].sum()

                    df_filtrado['ID_Estoque_Str'] = df_filtrado['ID_Estoque'].astype(str).str.strip().str.upper()
                    qtd_acc = df_filtrado[df_filtrado['ID_Estoque_Str'].astype(str).str.startswith('ACC_')].shape[0]
                    qtd_cel = df_filtrado[~df_filtrado['ID_Estoque_Str'].str.startswith('ACC_')].shape[0]

                    st.markdown(f"""<div style="background-color: rgba(255, 153, 0, 0.1); border: 1px solid #ff9900; padding: 20px; border-radius: 10px; text-align: center; margin-bottom: 20px; margin-top: 10px;"><p style="margin:0; font-size: 14px; opacity: 0.8; font-weight: bold; color: #ff9900;">TOTAL DE COMISSÕES A PAGAR</p><div style="margin:10px 0; color: #ff9900; font-size: 38px; font-weight: bold;">R$ {formata_br(total_comissao)}</div><p style="margin:0; font-size: 12px; color: #ff9900;">(Período: {data_inicio.strftime('%d/%m/%Y')} até {data_fim.strftime('%d/%m/%Y')} | Vendedor: {vendedor_sel})</p><hr style='border: 0; border-top: 1px dashed #ff9900; margin: 15px 0;'><div style='display:flex; justify-content:space-around; font-size: 14px; font-weight: bold; color: #ff9900;'><div>📱 Celulares: {qtd_cel}</div><div>🔌 Acessórios: {qtd_acc}</div></div></div>""", unsafe_allow_html=True)

                    if vendedor_sel == "TODOS" and not df_filtrado.empty:
                        st.markdown("<b>Resumo por Vendedor (Folha de Pagamento):</b>", unsafe_allow_html=True)
                        resumo_vend = df_filtrado.groupby('Vendedor')['Comissao_Vendedor'].sum().reset_index()
                        resumo_vend.columns = ['Nome do Vendedor', 'Total a Pagar (R$)']
                        resumo_vend['Total a Pagar (R$)'] = resumo_vend['Total a Pagar (R$)'].apply(lambda x: f"R$ {formata_br(x)}")
                        st.dataframe(resumo_vend, use_container_width=True, hide_index=True)
                        st.markdown("<hr>", unsafe_allow_html=True)

                    st.markdown("<b>Detalhamento das Vendas:</b>", unsafe_allow_html=True)
                    if not df_filtrado.empty:
                        df_detalhe = df_filtrado[['Data', 'Vendedor', 'Modelo', 'Cliente', 'Comissao_Vendedor']].copy()
                        df_detalhe['Comissao_Vendedor'] = df_detalhe['Comissao_Vendedor'].apply(lambda x: f"R$ {formata_br(x)}")
                        df_detalhe.rename(columns={'Comissao_Vendedor': 'Comissão Gerada'}, inplace=True)
                        st.dataframe(df_detalhe, use_container_width=True, hide_index=True)
                    else: st.info("Nenhuma comissão registrada para este filtro.")
                else: st.warning("⚠️ Selecione a data de início e a data de fim no calendário para processar os valores.")
            else: st.info("Nenhuma venda realizada ainda no sistema.")
        except Exception as e: st.info(f"Realize a primeira venda para gerar os relatórios de comissão. Detalhe: {e}")

    with aba_simulador:
        st.markdown("<div style='font-weight: bold; font-size: 16px; text-transform: uppercase;'>🔮 Simulador de Vendas Futuras</div>", unsafe_allow_html=True)
        st.markdown("<p style='font-size: 13px; color: #888;'>Simule metas de vendas para ver como elas salvariam ou impactariam o seu fluxo de caixa nos próximos 30 dias.</p>", unsafe_allow_html=True)
        with st.form("form_simulador"):
            c_sim1, c_sim2 = st.columns(2)
            sim_qtd = c_sim1.number_input("Pretendo vender (Qtd Aparelhos):", min_value=1, value=10, step=1)
            sim_val = c_sim2.number_input("Valor Médio de Cada Aparelho (R$):", min_value=0.0, value=1500.0, step=100.0)
            sim_pgto = st.selectbox("Qual será a forma de pagamento predominante?", ["BOLETO PARCELADO (PAYJOY - Recebe em 7 dias)", "BOLETO PARCELADO (AIVA - Recebe em 2 dias)", "PIX À VISTA"])
            
            if st.form_submit_button("🧪 CALCULAR IMPACTO NO CAIXA", type="primary"):
                faturamento_simulado = sim_qtd * sim_val
                if "PAYJOY" in sim_pgto: recebimento_estimado = faturamento_simulado * 0.98; dias_sim = 7
                elif "AIVA" in sim_pgto: recebimento_estimado = faturamento_simulado * 0.90; dias_sim = 2
                else: recebimento_estimado = faturamento_simulado; dias_sim = 0
                    
                saldo_base = saldo_projetado_periodo if 'saldo_projetado_periodo' in locals() else 0.0
                saldo_futuro_simulado = saldo_base + recebimento_estimado
                
                st.markdown("---")
                st.markdown(f"### Resultado da Simulação:")
                st.markdown(f"**Faturamento Extra Gerado:** R$ {formata_br(faturamento_simulado)}")
                st.markdown(f"**Líquido que entrará na conta (após taxas):** R$ {formata_br(recebimento_estimado)} em {dias_sim} dia(s).")
                st.markdown(f"**Seu Saldo Projetado subiria para:**")
                st.markdown(f"<div style='font-size: 32px; font-weight:bold; color:#00cc66;'>R$ {formata_br(saldo_futuro_simulado)}</div>", unsafe_allow_html=True)

    with aba_bancos:
        st.markdown("<div style='font-weight: bold; font-size: 16px; text-transform: uppercase;'>🏦 Atualizar Saldos Iniciais das Contas</div>", unsafe_allow_html=True)
        st.markdown("<p style='font-size: 13px; color: #888;'>Insira o valor que você já tinha nas contas antes de começar a usar o sistema para corrigir o seu Saldo Real de hoje.</p>", unsafe_allow_html=True)
        with st.form("form_saldos_iniciais"):
            df_bancos_atuais = df_b.copy()
            saldos_input = {}
            for idx, row in df_bancos_atuais.iterrows():
                banco_id = row['ID']; banco_nome = row['Nome']; banco_saldo = float(row['Saldo_Inicial'])
                saldos_input[banco_id] = st.number_input(f"Saldo Inicial Atual - {banco_nome} (R$)", value=banco_saldo, min_value=0.0, step=100.0, format="%.2f")

            if st.form_submit_button("💾 SALVAR SALDOS", type="primary"):
                for b_id, s_val in saldos_input.items():
                    supabase.table('bancos').update({'saldo_inicial': s_val}).eq('id', b_id).execute()
                st.cache_data.clear(); st.success("Saldos Iniciais atualizados com sucesso! Seu caixa real acaba de ser corrigido."); time.sleep(1.5); st.rerun()

    with aba_pendentes:
        st.markdown("<div style='font-weight: bold; font-size: 16px; text-transform: uppercase;'>✅ Dar Baixa ou Excluir Lançamentos</div>", unsafe_allow_html=True)
        col_cr, col_cp = st.columns(2, gap="large")
        with col_cr:
            st.markdown("<div style='color:#3b82f6; font-weight:bold; margin-bottom:10px;'>📥 CONTAS A RECEBER (Financeiras / Parcelas)</div>", unsafe_allow_html=True)
            df_cr_pend = df_cr[df_cr['Status'].str.upper() == 'PENDENTE'].copy() if not df_cr.empty else pd.DataFrame()
            if not df_cr_pend.empty:
                df_cr_pend['Status_Visual'] = df_cr_pend.apply(lambda r: "🔴 VENCIDO" if pd.notna(r['Venc_DT']) and r['Venc_DT'] < hoje_dt else "🟡 PENDENTE", axis=1)
                opcoes_cr = {f"ID {r['ID']} | {r['Vencimento']} | R$ {formata_br(r['Valor'])} | {str(r['Descricao'])[:20]}... [{r['Status_Visual']}]": r['ID'] for idx, r in df_cr_pend.iterrows()}
                sel_cr = st.selectbox("Selecione o Recebimento:", list(opcoes_cr.keys()))
                
                id_cr_sel = opcoes_cr[sel_cr]
                valor_total_cr = float(df_cr_pend[df_cr_pend['ID'] == id_cr_sel].iloc[0]['Valor'])
                banco_destino = st.selectbox("Conta Destino (Onde o dinheiro caiu):", ["CAIXA FÍSICO", "CONTA PIX", "BANCO SANTANDER", "BANCO BRADESCO"], key="banco_cr")
                data_pag_cr = st.date_input("Data do Recebimento:", hoje, key="dt_cr")
                
                valor_a_receber = st.number_input("Valor a Receber AGORA (R$):", min_value=0.01, max_value=valor_total_cr, value=valor_total_cr, step=10.0, format="%.2f", key="val_rec_parcial")
                
                b1, b2 = st.columns(2)
                if b1.button("✅ Confirmar Recebimento", type="primary", use_container_width=True, key="btn_ok_cr"):
                    restante = valor_total_cr - valor_a_receber
                    d_r = df_cr_pend[df_cr_pend['ID'] == id_cr_sel].iloc[0]['Descricao']
                    if restante <= 0.01:
                        supabase.table('contas_receber').update({'data_pagamento': data_pag_cr.strftime("%d/%m/%Y"), 'status': 'PAGO', 'conta_destino': banco_destino}).eq('id', id_cr_sel).execute()
                    else: supabase.table('contas_receber').update({'valor': restante, 'descricao': f"{d_r} (Restante após parcial)"}).eq('id', id_cr_sel).execute()
                    
                    supabase.table('movimentacoes').insert({'tipo': 'ENTRADA', 'descricao': f"BAIXA{' PARCIAL' if valor_a_receber < valor_total_cr else ''}: {d_r}", 'valor': valor_a_receber, 'data': data_pag_cr.strftime("%d/%m/%Y"), 'categoria': 'RECEBIMENTOS', 'conta': banco_destino, 'status': 'REALIZADO'}).execute()
                    st.cache_data.clear(); st.success("Baixa realizada!"); time.sleep(1.5); st.rerun()
                
                if b2.button("🗑️ Excluir Lançamento", type="secondary", use_container_width=True, key="btn_del_cr"):
                    supabase.table('contas_receber').delete().eq('id', id_cr_sel).execute()
                    st.cache_data.clear(); st.success("Lançamento excluído!"); time.sleep(1.5); st.rerun()
            else: st.info("Não há contas a receber pendentes.")
        
        with col_cp:
            st.markdown("<div style='color:#ff4d4d; font-weight:bold; margin-bottom:10px;'>💸 CONTAS A PAGAR (Despesas)</div>", unsafe_allow_html=True)
            df_cp_pend = df_cp[df_cp['Status'].str.upper() == 'PENDENTE'].copy() if not df_cp.empty else pd.DataFrame()
            if not df_cp_pend.empty:
                df_cp_pend['Status_Visual'] = df_cp_pend.apply(lambda r: "🔴 VENCIDO" if pd.notna(r['Venc_DT']) and r['Venc_DT'] < hoje_dt else "🟡 PENDENTE", axis=1)
                opcoes_cp = {f"ID {r['ID']} | {r['Vencimento']} | R$ {formata_br(r['Valor'])} | {str(r['Descricao'])[:20]} [{r['Status_Visual']}]": r['ID'] for idx, r in df_cp_pend.iterrows()}
                sel_cp = st.selectbox("Selecione a Despesa para Pagar:", list(opcoes_cp.keys()))
                
                id_cp_sel = opcoes_cp[sel_cp]
                valor_total_cp = float(df_cp_pend[df_cp_pend['ID'] == id_cp_sel].iloc[0]['Valor'])
                banco_origem = st.selectbox("Conta Origem (De onde saiu o dinheiro):", ["CAIXA FÍSICO", "CONTA PIX", "BANCO SANTANDER", "BANCO BRADESCO"], key="banco_cp")
                data_pag_cp = st.date_input("Data do Pagamento:", hoje, key="dt_cp")
                
                valor_a_pagar = st.number_input("Valor a Pagar AGORA (R$):", min_value=0.01, max_value=valor_total_cp, value=valor_total_cp, step=10.0, format="%.2f", key="val_pag_parcial")
                
                b1, b2 = st.columns(2)
                if b1.button("✅ Confirmar Pagamento", type="primary", use_container_width=True, key="btn_ok_cp"):
                    restante_p = valor_total_cp - valor_a_pagar
                    d_p = df_cp_pend[df_cp_pend['ID'] == id_cp_sel].iloc[0]['Descricao']
                    c_p_cat = df_cp_pend[df_cp_pend['ID'] == id_cp_sel].iloc[0]['Categoria']
                    if restante_p <= 0.01:
                        supabase.table('contas_pagar').update({'data_pagamento': data_pag_cp.strftime("%d/%m/%Y"), 'status': 'PAGO', 'conta_origem': banco_origem}).eq('id', id_cp_sel).execute()
                    else: supabase.table('contas_pagar').update({'valor': restante_p, 'descricao': f"{d_p} (Restante após parcial)"}).eq('id', id_cp_sel).execute()
                    
                    supabase.table('movimentacoes').insert({'tipo': 'SAIDA', 'descricao': f"BAIXA{' PARCIAL' if valor_a_pagar < valor_total_cp else ''}: {d_p}", 'valor': valor_a_pagar, 'data': data_pag_cp.strftime("%d/%m/%Y"), 'categoria': c_p_cat, 'conta': banco_origem, 'status': 'REALIZADO'}).execute()
                    st.cache_data.clear(); st.success("Conta Paga!"); time.sleep(1.5); st.rerun()
                
                if b2.button("🗑️ Excluir Despesa", type="secondary", use_container_width=True, key="btn_del_cp"):
                    supabase.table('contas_pagar').delete().eq('id', id_cp_sel).execute()
                    st.cache_data.clear(); st.success("Despesa excluída!"); time.sleep(1.5); st.rerun()
            else: st.info("Não há contas a pagar pendentes.")

    with aba_lancamentos:
        st.markdown("<div style='font-weight: bold; font-size: 16px; text-transform: uppercase;'>💸 Cadastro de Contas e Despesas</div>", unsafe_allow_html=True)
        with st.form("form_nova_despesa", clear_on_submit=True):
            c_desc, c_cat = st.columns([2, 1])
            d_desc = c_desc.text_input("Descrição / Nome da Conta (Ex: Aluguel Loja Centro)")
            d_cat = c_cat.selectbox("Categoria", ["Aluguel", "Salários", "Energia Elétrica", "Água", "Internet", "Marketing", "Impostos", "Contador", "Fornecedores", "Outros"])
            c_val, c_dt, c_rep = st.columns(3)
            d_valor = c_val.number_input("Valor (R$)", min_value=0.0, step=10.0, format="%.2f")
            d_dt = c_dt.date_input("Data do 1º Vencimento", hoje)
            d_rep = c_rep.number_input("Repetição (Quantos Meses?)", min_value=1, max_value=48, value=1, step=1, help="Deixe 1 para contas normais. Para Aluguel de 1 ano, digite 12.")
            if st.form_submit_button("💾 LANÇAR CONTA A PAGAR", type="primary"):
                if d_desc.strip() == "" or d_valor <= 0: st.error("A descrição e o valor são obrigatórios!")
                else:
                    for i in range(d_rep):
                        dp = d_dt + pd.DateOffset(months=i)
                        supabase.table('contas_pagar').insert({'descricao': d_desc.upper() + (f" ({i+1}/{d_rep})" if d_rep > 1 else ""), 'categoria': d_cat.upper(), 'fornecedor': "-", 'vencimento': dp.strftime("%d/%m/%Y"), 'valor': d_valor, 'data_pagamento': "", 'status': "PENDENTE", 'conta_origem': "", 'repeticao': f"{i+1}/{d_rep}"}).execute()
                    st.cache_data.clear(); st.success(f"Lançamento gravado com sucesso! ({d_rep} meses projetados no fluxo)"); time.sleep(1.5); st.rerun()

# --- MÓDULO 3: EXTRATO (SÓ PARA GESTOR) ---
elif st.session_state.menu_selecionado == "FATURAMENTO":
    st.markdown("<div style='color: #888; font-size: 14px; letter-spacing: 1px; margin-top: -10px; margin-bottom: 20px;'>SUPORTE SMART &nbsp;>&nbsp; <span style='font-weight: bold;'>EXTRATO REAL DE CAIXA E CANCELAMENTOS</span></div>", unsafe_allow_html=True)
    df_b, df_cp, df_cr, df_mov = carregar_financeiro()
    
    aba_extrato, aba_cancelar = st.tabs(["📄 Extrato Bancário", "🔄 Cancelar Venda / Devolver Estoque"])
    
    with aba_extrato:
        st.markdown("<div style='font-weight: bold; font-size: 16px; text-transform: uppercase; margin-bottom: 15px; margin-top: 10px;'>📄 Extrato Bancário da Loja (Movimentações Reais)</div>", unsafe_allow_html=True)
        if not df_mov.empty:
            html = "<table class='tabela-leve'><tr><th>ID</th><th>Data</th><th>Tipo</th><th>Descrição</th><th>Conta</th><th>Valor</th></tr>"
            # MÁQUINA: Renderiza apenas as últimas 200 movimentações para não explodir a tela
            for index, row in df_mov.tail(200).iloc[::-1].iterrows():
                data_str = str(row['Data']).split(" ")[0] if pd.notna(row['Data']) else "-"
                desc_completa = str(row['Descricao']) if pd.notna(row['Descricao']) else ""
                conta = str(row['Conta']) if pd.notna(row['Conta']) else "-"
                valor = float(row['Valor']) if pd.notna(row['Valor']) else 0.0
                if str(row['Tipo']).upper() == "SAIDA": valor_html = f"<span style='color:#ff4d4d; font-weight:bold;'>- R$ {formata_br(valor)}</span>"
                else: valor_html = f"<span style='color:#00cc66; font-weight:bold;'>+ R$ {formata_br(valor)}</span>"
                html += f"<tr><td>{row['ID']}</td><td>{data_str}</td><td><b>{row['Tipo']}</b></td><td>{desc_completa}</td><td>{conta}</td><td>{valor_html}</td></tr>"
            html += "</table>"
            st.markdown(html, unsafe_allow_html=True)
        else: st.info("Nenhuma movimentação realizada ainda.")
        
        st.markdown("<br><hr style='border: 1px solid var(--secondary-background-color);'><br>", unsafe_allow_html=True)
        st.markdown("<div style='font-weight: bold; font-size: 16px; text-transform: uppercase; margin-bottom: 15px;'>❌ Estornar Movimentação Real do Extrato</div>", unsafe_allow_html=True)
        st.warning("⚠️ **ATENÇÃO:** Se for uma VENDA DE PRODUTO, use a aba 'Cancelar Venda' ao lado para devolver o produto ao estoque e cancelar a comissão. Este botão serve apenas para apagar registos errados do caixa.")
        
        if not df_mov.empty:
            opcoes_cancelamento = {f"ID {r['ID']} | {str(r['Data']).split(' ')[0]} | {str(r['Descricao'])[:40]}... (R$ {formata_br(r['Valor'])})": r['ID'] for idx, r in df_mov.tail(100).iterrows()}
            venda_selecionada = st.selectbox("Selecione a Movimentação Financeira para apagar:", list(opcoes_cancelamento.keys()))
            id_para_excluir = opcoes_cancelamento[venda_selecionada]
            if st.button("❌ APAGAR REGISTO DO EXTRATO", type="secondary"):
                supabase.table('movimentacoes').delete().eq('id', id_para_excluir).execute()
                st.success(f"Movimentação ID {id_para_excluir} estornada com sucesso!"); st.cache_data.clear(); st.rerun()
    
    with aba_cancelar:
        st.markdown("<div style='font-weight: bold; font-size: 16px; text-transform: uppercase; margin-bottom: 15px; margin-top: 10px;'>🔄 Cancelamento e Devolução de Produtos</div>", unsafe_allow_html=True)
        st.markdown("<span style='font-size: 13px; color: #888;'>Ao cancelar uma venda aqui, o sistema automaticamente devolve o aparelho ou acessório ao estoque, lança um Estorno Negativo no caixa e retira a comissão da folha do vendedor.</span>", unsafe_allow_html=True)
        
        df_saidas_canc = carregar_saidas()
        if not df_saidas_canc.empty:
            op_vendas = {f"Data: {str(r['Data']).split()[0][:10]} | Cliente: {str(r['Cliente'])[:15]} | {str(r['Modelo'])[:20]} (R$ {formata_br(r['Valor_Venda'])})": r['ID'] for idx, r in df_saidas_canc.tail(50).iterrows()}
            sel_venda = st.selectbox("Selecione o produto vendido para cancelar:", list(op_vendas.keys()))
            v_id = op_vendas[sel_venda]
            
            if st.button("🚫 CANCELAR VENDA E DEVOLVER AO ESTOQUE", type="primary"):
                d_v = df_saidas_canc[df_saidas_canc['ID'] == v_id].iloc[0]
                v_imei = str(d_v['IMEI']).strip()
                v_modelo = str(d_v['Modelo']).strip()
                v_valor = float(d_v['Valor_Venda'])
                v_id_est = str(d_v['ID_Estoque'])
                v_qtd = float(d_v.get('Quantidade', 1) if 'Quantidade' in d_v else 1)
                
                if v_imei != '-' and v_imei != 'nan':
                    supabase.table('estoque').update({'status': 'Em Estoque', 'cliente_venda': '', 'pagamento_venda': ''}).eq('imei', v_imei).execute()
                elif v_id_est.startswith("ACC_"):
                    acc_id = v_id_est.split("_")[1]
                    acc_db = supabase.table('acessorios').select('quantidade').eq('id', acc_id).execute()
                    if acc_db.data:
                        nova_qtd = float(acc_db.data[0]['quantidade']) + v_qtd
                        supabase.table('acessorios').update({'quantidade': nova_qtd}).eq('id', acc_id).execute()
                
                supabase.table('saidas').delete().eq('id', v_id).execute()
                supabase.table('movimentacoes').insert({'tipo': 'SAIDA', 'descricao': f"ESTORNO/DEVOLUÇÃO: {v_modelo}", 'valor': v_valor, 'data': hoje.strftime("%d/%m/%Y"), 'categoria': 'ESTORNO', 'conta': 'CAIXA FÍSICO', 'status': 'REALIZADO'}).execute()
                st.success("✅ Venda cancelada com sucesso! Produto devolvido ao estoque e caixa atualizado."); time.sleep(2.5); st.cache_data.clear(); st.rerun()
        else: st.info("Nenhuma venda de produto registrada para cancelamento.")

# --- MÓDULO: CONFIGURAÇÕES (SÓ PARA GESTOR) ---
elif st.session_state.menu_selecionado == "CONFIGURACOES":
    st.markdown("<div style='color: #888; font-size: 14px; letter-spacing: 1px; margin-top: -10px; margin-bottom: 20px;'>SUPORTE SMART &nbsp;>&nbsp; <span style='font-weight: bold;'>CONFIGURAÇÕES DO SISTEMA (NUVEM)</span></div>", unsafe_allow_html=True)
    
    config = carregar_config()
    col_conf1, col_conf2 = st.columns([1.2, 1], gap="large")
    
    with col_conf1:
        st.markdown("<div style='margin-top:0; margin-bottom: 20px; font-weight: bold; font-size: 16px; text-transform: uppercase;'>⚙️ Controle de Limites e Margens Mínimas</div>", unsafe_allow_html=True)
        with st.form("form_config"):
            c1, c2 = st.columns(2)
            m_celular = c1.number_input("Margem Mínima p/ Celulares (%)", value=float(config.get("margem_celular_pct", 100.0)), min_value=0.0, step=5.0, format="%.1f")
            m_acessorio = c2.number_input("Margem Mínima p/ Acessórios (%)", value=float(config.get("margem_acessorio_pct", 100.0)), min_value=0.0, step=5.0, format="%.1f")
            c3, c4 = st.columns(2)
            limite_premium = c3.number_input("Custo Limite p/ Premium (R$)", value=float(config.get("limite_custo_premium", 900.0)), min_value=0.0, step=50.0, format="%.2f")
            dias_garantia = c4.number_input("Dias de Garantia Padrão", value=int(config.get("dias_garantia", 90)), min_value=0, step=1)
            
            salvar_btn = st.form_submit_button("💾 SALVAR CONFIGURAÇÕES", type="primary", use_container_width=True)
            if salvar_btn:
                salvar_config({
                    "margem_celular_pct": m_celular, 
                    "margem_acessorio_pct": m_acessorio, 
                    "limite_custo_premium": limite_premium, 
                    "comissao_celular_pct": config.get("comissao_celular_pct", 1.0), 
                    "comissao_acessorio_pct": config.get("comissao_acessorio_pct", 5.0),
                    "dias_garantia": dias_garantia
                })
                st.cache_data.clear()
                st.success("Configurações salvas!"); time.sleep(1); st.rerun()

    with col_conf2:
        st.markdown("<div style='margin-top:0; margin-bottom: 20px; font-weight: bold; font-size: 16px; text-transform: uppercase;'>👥 Gestão de Acessos (Planilha Editável)</div>", unsafe_allow_html=True)
        st.markdown("<span style='font-size: 13px; color: #888;'>Adicione, edite ou apague os acessos da equipa diretamente na tabela abaixo clicando duas vezes na célula.</span>", unsafe_allow_html=True)
        
        df_usuarios = fetch_df('usuarios', ['id', 'usuario', 'senha', 'nome_completo', 'perfil'])
        df_usuarios.rename(columns={'id': 'ID', 'usuario': 'Usuario', 'senha': 'Senha', 'nome_completo': 'Nome_Completo', 'perfil': 'Perfil'}, inplace=True)
            
        df_editado = st.data_editor(
            df_usuarios, num_rows="dynamic", use_container_width=True,
            column_config={
                "Perfil": st.column_config.SelectboxColumn("Perfil", options=["GESTOR", "VENDEDOR"], required=True),
                "Usuario": st.column_config.TextColumn("Login", required=True),
                "Senha": st.column_config.TextColumn("Senha", required=True),
                "Nome_Completo": st.column_config.TextColumn("Nome Completo", required=True),
                "ID": st.column_config.NumberColumn("ID", disabled=True)
            }
        )
        
        if st.button("💾 SALVAR PLANILHA DE USUÁRIOS", type="primary", use_container_width=True):
            supabase.table('usuarios').delete().neq('id', -1).execute() 
            for _, r in df_editado.iterrows():
                supabase.table('usuarios').insert({'usuario': str(r['Usuario']), 'senha': str(r['Senha']), 'nome_completo': str(r['Nome_Completo']), 'perfil': str(r['Perfil'])}).execute()
            st.success("Acessos atualizados com sucesso na nuvem!"); time.sleep(1); st.rerun()

    st.markdown("<hr style='border: 1px solid var(--secondary-background-color); margin-top: 30px; margin-bottom: 20px;'>", unsafe_allow_html=True)
    st.markdown("<div style='font-weight: bold; font-size: 16px; text-transform: uppercase;'>💾 Backup de Emergência (CSV)</div>", unsafe_allow_html=True)
    st.markdown("<span style='font-size: 13px; color: #888; margin-bottom: 10px; display: block;'>Baixe todos os dados do sistema num ficheiro ZIP com tabelas CSV.</span>", unsafe_allow_html=True)
    
    def criar_zip_backup():
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for table in ['clientes', 'estoque', 'saidas', 'bancos', 'contas_pagar', 'contas_receber', 'movimentacoes', 'acessorios', 'usuarios', 'config']:
                df_bck = fetch_df(table, [])
                if not df_bck.empty: zip_file.writestr(f"{table}.csv", df_bck.to_csv(index=False))
        return zip_buffer.getvalue()

    st.download_button(label="📥 BAIXAR BACKUP COMPLETO DO SISTEMA (.ZIP)", data=criar_zip_backup(), file_name=f"Backup_SuporteSmart_{datetime.datetime.now().strftime('%d-%m-%Y_%H-%M')}.zip", mime="application/zip", type="primary")
    st.markdown("<br>", unsafe_allow_html=True)
    
    st.markdown("<div style='margin-top:0; margin-bottom: 20px; font-weight: bold; font-size: 16px; text-transform: uppercase;'>🚨 Resetar Banco de Dados</div>", unsafe_allow_html=True)
    with st.expander("Clique aqui para apagar todos os dados do sistema"):
        st.warning("⚠️ **Atenção!** Apaga TODOS os Clientes, Estoque e Fluxo de Caixa. É irreversível!")
        senha_zerar = st.text_input("Digite a senha do gestor:", type="password", key="senha_zerar")
        if st.button("🗑️ APAGAR TUDO E ZERAR", type="primary", use_container_width=True):
            if senha_zerar == "admin123":
                for table in ['clientes', 'estoque', 'saidas', 'contas_pagar', 'contas_receber', 'movimentacoes', 'acessorios', 'bancos']:
                    supabase.table(table).delete().neq('id', -1).execute()
                supabase.table('bancos').insert([{'nome':'CAIXA FÍSICO','saldo_inicial':0},{'nome':'CONTA PIX','saldo_inicial':0},{'nome':'BANCO SANTANDER','saldo_inicial':0},{'nome':'BANCO BRADESCO','saldo_inicial':0}]).execute()
                st.cache_data.clear(); st.success("Sistema zerado na nuvem!"); time.sleep(2); st.rerun()
            else: st.error("Senha incorreta!")
