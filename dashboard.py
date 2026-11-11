import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st

st.set_page_config(
    page_title="Vaga Inteligente",
    page_icon="🚗",
    layout="wide"
)

URL = st.secrets["SUPABASE_URL"].rstrip("/")
KEY = st.secrets["SUPABASE_ANON_KEY"]
FUSO = ZoneInfo("America/Sao_Paulo")
PI_OFFLINE_APOS = 30  # s sem sinal de vida → Raspberry offline

STATUS_COMANDO = {
    "pendente": "⏳ aguardando o Raspberry",
    "executando": "⚙️ executando",
    "executado": "✅ executado",
    "recusado": "⛔ recusado pelo Raspberry",
    "expirado": "⌛ expirou (Raspberry não respondeu)",
    "erro": "❌ erro",
}

STATUS_RFID = {
    "AUTORIZADO": "✅ AUTORIZADO",
    "NEGADO": "⛔ NEGADO",
    "LOTADO": "🅿️ LOTADO",
    "FALHA_ABERTURA": "⚠️ FALHA NA ABERTURA",
}

ESTADO_AUTO = {
    "inativo": "inativo",
    "contagem_10_segundos": "contagem para fechar",
    "fechado_teste_bancada": "fechou sozinho (teste de bancada)",
    "cancelado_pelo_dashboard": "cancelado por um comando manual",
    "reagendado": "reagendado por um novo cartão",
    "cancelado_posicao_alterada": "cancelado (a cancela mudou de posição)",
    "desabilitado_ou_sessao_expirada": "desabilitado ou janela de teste expirada",
    "bloqueado": "bloqueado",
}


class SessaoExpirada(Exception):
    pass


# ---------------------------------------------------------------------------
# Acesso ao Supabase
# ---------------------------------------------------------------------------
def cabecalhos(token=None):
    return {
        "apikey": KEY,
        "Authorization": f"Bearer {token or KEY}",
    }


def consultar(tabela, params, token=None):
    resposta = requests.get(
        f"{URL}/rest/v1/{tabela}",
        params=params,
        headers=cabecalhos(token),
        timeout=10
    )
    if resposta.status_code == 401 and token:
        raise SessaoExpirada()
    resposta.raise_for_status()
    return resposta.json()


@st.cache_data(ttl=2)
def buscar_vagas():
    return consultar("status_vagas", {
        "select": "vaga_id,ocupada,entrada,atualizado_em",
        "order": "vaga_id.asc"
    })


@st.cache_data(ttl=2)
def buscar_status_sistema():
    linhas = consultar("status_sistema", {"select": "*", "id": "eq.1"})
    return linhas[0] if linhas else None


@st.cache_data(ttl=5)
def buscar_permanencias(limite=25):
    return consultar("permanencias", {
        "select": "vaga_id,entrada,saida,duracao_segundos",
        "order": "saida.desc",
        "limit": limite
    })


def buscar_eventos(token, limite=25):
    return consultar("eventos", {
        "select": "horario,tipo,descricao",
        "order": "horario.desc,id_local.desc",
        "limit": limite
    }, token)


def buscar_ultima_leitura(token):
    linhas = consultar("status_privado", {
        "select": "rfid_ultima_leitura",
        "id": "eq.1"
    }, token)
    return linhas[0]["rfid_ultima_leitura"] if linhas else None


def buscar_comandos(token, limite=5):
    return consultar("comandos_cancela", {
        "select": "id,acao,status,mensagem,criado_em",
        "order": "id.desc",
        "limit": limite
    }, token)


def pedir_comando(token, acao):
    resposta = requests.post(
        f"{URL}/rest/v1/comandos_cancela",
        json={"acao": acao},
        headers={**cabecalhos(token), "Prefer": "return=minimal"},
        timeout=10
    )
    if resposta.status_code == 401:
        raise SessaoExpirada()
    resposta.raise_for_status()


def entrar(email, senha):
    resposta = requests.post(
        f"{URL}/auth/v1/token",
        params={"grant_type": "password"},
        json={"email": email, "password": senha},
        headers={"apikey": KEY},
        timeout=10
    )
    if resposta.status_code in (400, 401):
        return None
    resposta.raise_for_status()
    dados = resposta.json()
    return {
        "token": dados["access_token"],
        "email": dados.get("user", {}).get("email", email),
        "expira": time.time() + int(dados.get("expires_in", 3600)) - 60,
    }


def sessao_atual():
    sessao = st.session_state.get("sessao")
    if sessao and time.time() >= sessao["expira"]:
        st.session_state.pop("sessao", None)
        st.session_state["aviso_login"] = "Sua sessão expirou. Entre de novo."
        return None
    return sessao


def sessao_expirou():
    st.session_state.pop("sessao", None)
    st.session_state["aviso_login"] = "Sua sessão expirou. Entre de novo."
    st.rerun()


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------
def ler_data(texto):
    if not texto:
        return None
    return datetime.fromisoformat(texto.replace("Z", "+00:00"))


def formatar_duracao(segundos):
    segundos = max(0, int(segundos or 0))
    horas, resto = divmod(segundos, 3600)
    minutos, segundos = divmod(resto, 60)
    return f"{horas:02d}:{minutos:02d}:{segundos:02d}"


def tempo_permanencia(entrada):
    inicio = ler_data(entrada)
    if not inicio:
        return "00:00:00"
    agora = datetime.now().astimezone()
    return formatar_duracao((agora - inicio).total_seconds())


def hora_local(texto):
    data = ler_data(texto)
    return data.astimezone(FUSO).strftime("%d/%m %H:%M:%S") if data else "-"


def pi_online(sistema):
    visto = ler_data(sistema.get("pi_visto_em")) if sistema else None
    if not visto:
        return False, None
    segundos = (datetime.now().astimezone() - visto).total_seconds()
    return segundos <= PI_OFFLINE_APOS, segundos


# ---------------------------------------------------------------------------
# Tela
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("🔐 Acesso")
    sessao = sessao_atual()
    if sessao:
        st.success(f"Conectado como {sessao['email']}")
        if st.button("Sair", width="stretch"):
            st.session_state.pop("sessao", None)
            st.rerun()
    else:
        if aviso := st.session_state.pop("aviso_login", None):
            st.warning(aviso)
        st.caption("Entre para controlar a cancela e ver os eventos e cartões RFID.")
        with st.form("login"):
            email = st.text_input("E-mail")
            senha = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar", width="stretch"):
                try:
                    nova = entrar(email.strip(), senha)
                except requests.RequestException as erro:
                    st.error(f"Falha de comunicação: {erro}")
                else:
                    if nova:
                        st.session_state["sessao"] = nova
                        st.rerun()
                    else:
                        st.error("E-mail ou senha incorretos.")


st.title("🚗 Vaga Inteligente")
st.caption("Monitoramento online - Raspberry Pi 4B")


@st.fragment(run_every="5s")
def monitoramento():
    try:
        vagas = buscar_vagas()
        sistema = buscar_status_sistema()
    except Exception as erro:
        st.error(f"Falha de comunicação: {erro}")
        return

    online, segundos = pi_online(sistema)
    if online:
        st.success("🟢 Raspberry online")
    elif segundos is None:
        st.warning("⚪ O Raspberry ainda não se conectou ao banco online.")
    else:
        st.error(
            f"🔴 Raspberry offline: último sinal há {int(segundos // 60)} min "
            f"{int(segundos % 60)} s. As informações abaixo podem estar desatualizadas."
        )

    if not vagas:
        st.warning("Nenhuma vaga cadastrada.")
        return

    ocupadas = sum(v["ocupada"] for v in vagas)

    c1, c2, c3 = st.columns(3)
    c1.metric("Total de vagas", len(vagas))
    c2.metric("Vagas livres", len(vagas) - ocupadas)
    c3.metric("Vagas ocupadas", ocupadas)

    st.divider()

    colunas = st.columns(len(vagas))

    for coluna, vaga in zip(colunas, vagas):
        with coluna:
            st.subheader(f"Vaga {vaga['vaga_id']}")

            if vaga["ocupada"]:
                st.error("🔴 OCUPADA")
                st.metric(
                    "Tempo estacionado",
                    tempo_permanencia(vaga["entrada"])
                )
            else:
                st.success("🟢 LIVRE")
                st.metric("Tempo estacionado", "00:00:00")


def mostrar_fechamento_auto(sistema):
    estado = sistema.get("auto_estado")
    if not estado:
        return
    texto = ESTADO_AUTO.get(estado, estado)
    fecha_em = ler_data(sistema.get("auto_fecha_em"))
    if estado == "contagem_10_segundos" and fecha_em:
        restante = max(0, int((fecha_em - datetime.now().astimezone()).total_seconds()))
        texto = f"fecha em {restante} s"
    st.write("Fechamento RFID:", texto)
    if sistema.get("auto_modo_bancada"):
        st.warning("Modo sem ultrassônico: exclusivo para bancada sem veículos ou pessoas.")
    else:
        st.info("Fechamento sem ultrassônico desabilitado.")


def mostrar_cancela(sistema, online, sessao):
    st.subheader("🚧 Cancela SG90")
    aberta = sistema.get("cancela_aberta")
    if not online:
        st.write("Posição: desconhecida (Raspberry offline)")
    elif not sistema.get("api_online"):
        st.write("Posição: desconhecida (o programa da cancela no Raspberry não responde)")
    elif aberta is None:
        st.write("Posição: ainda não comandada desde que o Raspberry ligou")
    else:
        st.write("Posição:", "**ABERTA**" if aberta else "**FECHADA**")
    st.caption("Posição comandada: o SG90 não tem sensor que confirme onde a haste parou.")
    if online and sistema.get("api_online"):
        mostrar_fechamento_auto(sistema)

    if not sessao:
        st.info("Entre pela barra lateral para abrir ou fechar a cancela.")
        return

    pode_mandar = online and bool(sistema.get("api_online"))
    fechamento = bool(sistema.get("fechamento_habilitado"))

    st.warning("Só acione com a trajetória da haste livre: o sensor ultrassônico ainda não protege a cancela.")
    b1, b2 = st.columns(2)
    if b1.button("⬆️ Abrir", width="stretch", disabled=not pode_mandar):
        pedir_comando(sessao["token"], "abrir")
        st.toast("Pedido de abrir enviado ao Raspberry")
    if b2.button("⬇️ Fechar", width="stretch",
                 disabled=not (pode_mandar and fechamento)):
        pedir_comando(sessao["token"], "fechar")
        st.toast("Pedido de fechar enviado ao Raspberry")
    if pode_mandar and not fechamento:
        st.caption("Fechar está desligado no Raspberry (modo de teste VAGA_FECHAMENTO_TESTE).")

    comandos = buscar_comandos(sessao["token"])
    if comandos:
        st.write("Últimos comandos")
        for c in comandos:
            linha = (
                f"`{hora_local(c['criado_em'])}` **{c['acao']}** · "
                f"{STATUS_COMANDO.get(c['status'], c['status'])}"
            )
            if c.get("mensagem") and c["status"] != "executado":
                linha += f" — {c['mensagem']}"
            st.markdown(linha)


def mostrar_rfid(sistema, online, sessao):
    st.subheader("💳 Cartão RFID")
    if not online:
        st.write("Leitor: desconhecido (Raspberry offline)")
    elif sistema.get("rfid_monitor_ativo") is None:
        st.write("Leitor: sem informação do Raspberry")
    else:
        st.write("Monitor:", "rodando" if sistema.get("rfid_monitor_ativo") else "parado")
        conectado = sistema.get("rfid_leitor_conectado")
        if conectado is not None:  # a API antiga do Pi não informa
            st.write("Leitor RC522:", "conectado" if conectado else "indisponível")
        if sistema.get("rfid_ultimo_erro"):
            st.caption("Último erro: " + str(sistema["rfid_ultimo_erro"]))

    if not sessao:
        st.info("Entre pela barra lateral para ver o último cartão lido.")
        return

    leitura = buscar_ultima_leitura(sessao["token"])
    if leitura:
        st.write("Último cartão:", f"**{leitura.get('nome') or '-'}**")
        st.write("Status:", STATUS_RFID.get(leitura.get("status"), leitura.get("status")))
        st.caption(f"{leitura.get('mensagem', '')} · {hora_local(leitura.get('horario'))}")
    else:
        st.caption("Nenhum cartão lido ainda.")


@st.fragment(run_every="3s")
def painel():
    try:
        sistema = buscar_status_sistema() or {}
    except Exception as erro:
        st.error(f"Falha de comunicação: {erro}")
        return
    online, _ = pi_online(sistema)
    sessao = sessao_atual()

    col_cancela, col_rfid = st.columns(2)
    try:
        with col_cancela:
            mostrar_cancela(sistema, online, sessao)
        with col_rfid:
            mostrar_rfid(sistema, online, sessao)
    except SessaoExpirada:
        sessao_expirou()
    except requests.RequestException as erro:
        st.error(f"Falha de comunicação: {erro}")


@st.fragment(run_every="10s")
def historico():
    with st.expander("📜 Eventos e histórico", expanded=True):
        st.write("**Permanências encerradas**")
        try:
            permanencias = buscar_permanencias()
        except requests.RequestException as erro:
            st.warning(f"Histórico indisponível: {erro}")
            permanencias = None
        if permanencias:
            st.dataframe([{
                "Vaga": p["vaga_id"],
                "Entrada": hora_local(p["entrada"]),
                "Saída": hora_local(p["saida"]),
                "Duração": formatar_duracao(p["duracao_segundos"]),
            } for p in permanencias], width="stretch", hide_index=True)
        elif permanencias is not None:
            st.caption("Nenhuma permanência encerrada ainda.")

        st.write("**Últimos eventos**")
        sessao = sessao_atual()
        if not sessao:
            st.info("Entre pela barra lateral para ver os eventos (incluem nomes dos cartões).")
            return
        try:
            eventos = buscar_eventos(sessao["token"])
        except SessaoExpirada:
            sessao_expirou()
            return
        except requests.RequestException as erro:
            st.warning(f"Eventos indisponíveis: {erro}")
            return
        if eventos:
            st.dataframe([{
                "Horário": hora_local(e["horario"]),
                "Tipo": e["tipo"],
                "Descrição": e["descricao"],
            } for e in eventos], width="stretch", hide_index=True)
        else:
            st.caption("Nenhum evento ainda.")


monitoramento()
st.divider()
painel()
st.divider()
historico()
st.caption("Dados recebidos do banco online.")
