
import random
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

from banco import (
    inicializar_banco,
    listar_vagas,
    listar_eventos,
    listar_permanencias,
    registrar_evento
)

API = "http://127.0.0.1:8000"

st.set_page_config(
    page_title="Vaga Inteligente",
    page_icon="🚗",
    layout="wide"
)

inicializar_banco()

st.title("🚗 Vaga Inteligente")
st.caption("Raspberry Pi 4B | Streamlit + FastAPI + SQLite")


def api_get(caminho):
    resposta = requests.get(API + caminho, timeout=5)
    resposta.raise_for_status()
    return resposta.json()


def api_post(caminho, dados=None):
    resposta = requests.post(
        API + caminho, json=dados, timeout=5
    )
    resposta.raise_for_status()
    return resposta.json()


def formatar_tempo(segundos):
    segundos = max(0, int(segundos))
    horas, resto = divmod(segundos, 3600)
    minutos, segundos = divmod(resto, 60)
    return f"{horas:02d}:{minutos:02d}:{segundos:02d}"


def tempo_na_vaga(entrada):
    if not entrada:
        return "00:00:00"

    inicio = datetime.fromisoformat(entrada)
    agora = datetime.now().astimezone()
    return formatar_tempo((agora - inicio).total_seconds())


@st.fragment(run_every="2s")
def monitoramento_vagas():
    st.subheader("🅿️ Monitoramento das vagas")

    try:
        sensores = api_get("/sensores/status")
        monitor_ativo = sensores["monitor_ativo"]
    except requests.RequestException:
        monitor_ativo = False

    if monitor_ativo:
        st.success("📡 Sensores físicos conectados")
    else:
        st.error("⚠️ Monitoramento físico indisponível")

    vagas = listar_vagas()
    ocupadas = sum(v["ocupada"] for v in vagas)
    livres = len(vagas) - ocupadas

    c1, c2, c3 = st.columns(3)
    c1.metric("Total", len(vagas))
    c2.metric("Livres", livres)
    c3.metric("Ocupadas", ocupadas)

    colunas = st.columns(2)

    for vaga, coluna in zip(vagas, colunas):
        with coluna:
            st.markdown(f"### Vaga {vaga['id']}")

            if not monitor_ativo:
                st.warning("Estado não confirmado")
            elif vaga["ocupada"]:
                st.error("🔴 OCUPADA")
            else:
                st.success("🟢 LIVRE")

            st.metric(
                "Tempo estacionado",
                tempo_na_vaga(vaga["entrada"])
                if vaga["ocupada"] else "00:00:00"
            )

            if vaga["entrada"]:
                st.caption(
                    "Entrada: " +
                    datetime.fromisoformat(
                        vaga["entrada"]
                    ).strftime("%d/%m/%Y %H:%M:%S")
                )

    st.caption(
        "Atualização automática a cada 2 segundos."
    )


monitoramento_vagas()
st.divider()

# ----------------------------------------
# CANCELA (AINDA EM SIMULAÇÃO)
# ----------------------------------------

st.subheader("🚧 Controle manual da cancela")
st.info("A cancela ainda está em modo simulação.")

try:
    estado = api_get("/status")
except requests.RequestException:
    estado = None
    st.error("API offline. Verifique a porta 8000.")

if estado:
    aberta = estado["cancela_aberta"]
    obstaculo = estado["obstaculo"]

    col1, col2 = st.columns(2)

    with col1:
        if aberta:
            st.success("🟢 CANCELA ABERTA")
        else:
            st.error("🔴 CANCELA FECHADA")

    with col2:
        if obstaculo:
            st.warning("⚠️ Veículo sob a cancela")
        else:
            st.success("✅ Área livre")

    col1, col2 = st.columns(2)

    with col1:
        if st.button(
            "🔓 Abrir cancela",
            disabled=aberta,
            use_container_width=True
        ):
            try:
                st.session_state.resultado = api_post(
                    "/cancela/abrir"
                )
                st.rerun()
            except requests.RequestException as erro:
                st.error(str(erro))

    with col2:
        if st.button(
            "🔒 Fechar cancela",
            disabled=not aberta or obstaculo,
            use_container_width=True
        ):
            try:
                st.session_state.resultado = api_post(
                    "/cancela/fechar"
                )
                st.rerun()
            except requests.RequestException as erro:
                st.error(str(erro))

    if "resultado" in st.session_state:
        resultado = st.session_state.resultado
        if resultado["sucesso"]:
            st.success(resultado["mensagem"])
        else:
            st.warning(resultado["mensagem"])

    st.divider()
    st.subheader("📡 Sensor ultrassônico")
    st.caption("Simulação — HC-SR04 ainda não integrado.")

    presente = st.toggle(
        "Simular veículo sob a cancela",
        value=obstaculo
    )

    if presente != obstaculo:
        try:
            api_post(
                "/simulacao/obstaculo",
                {"presente": presente}
            )
            st.rerun()
        except requests.RequestException as erro:
            st.error(str(erro))

    distancia = (
        random.uniform(5, 15)
        if obstaculo else random.uniform(40, 100)
    )
    st.metric("Distância simulada", f"{distancia:.1f} cm")

st.divider()


# ----------------------------------------
# RFID FISICO
# ----------------------------------------

@st.fragment(run_every="2s")
def painel_rfid():
    st.subheader("💳 Controle de acesso RFID")

    try:
        dados = api_get("/rfid/status")
    except requests.RequestException:
        st.error("Não foi possível consultar o RFID.")
        return

    if not dados["monitor_ativo"]:
        st.error("⚠️ Leitor RFID indisponível")
        return

    st.success("📡 Leitor RC522 ativo")
    leitura = dados["ultima_leitura"]

    if not leitura:
        st.info("Aguardando aproximação de um cartão...")
        return

    status = leitura["status"]

    if status == "AUTORIZADO":
        st.success("✅ ACESSO AUTORIZADO")
    elif status == "LOTADO":
        st.warning("⚠️ ESTACIONAMENTO LOTADO")
    else:
        st.error("⛔ ACESSO NEGADO")

    col1, col2 = st.columns(2)

    with col1:
        st.metric("Último UID", leitura["uid"])
        st.write("**Cartão:**", leitura["nome"])

    with col2:
        st.write("**Resultado:**", leitura["mensagem"])
        st.write(
            "**Horário:**",
            datetime.fromisoformat(
                leitura["horario"]
            ).strftime("%d/%m/%Y %H:%M:%S")
        )

    st.caption(
        "Leitura física pelo RC522. "
        "A cancela ainda não é acionada automaticamente."
    )


painel_rfid()
st.divider()

# ----------------------------------------
# OLED SIMULADO
# ----------------------------------------

st.subheader("📟 Display OLED")
st.caption("Prévia virtual — display físico pendente.")

if estado:
    mensagem_oled = (
        "CANCELA ABERTA"
        if estado["cancela_aberta"]
        else "AGUARDANDO CARTAO"
    )

    if estado["obstaculo"]:
        mensagem_oled = "VEICULO DETECTADO"

    st.code(mensagem_oled, language=None)

st.divider()

# ----------------------------------------
# HISTÓRICOS
# ----------------------------------------

@st.fragment(run_every="2s")
def historicos():
    st.subheader("📊 Histórico de permanências")

    permanencias = listar_permanencias()

    if permanencias:
        df = pd.DataFrame(permanencias)
        df["Tempo"] = df.apply(
            lambda linha: (
                formatar_tempo(linha["duracao_segundos"])
                if pd.notna(linha["duracao_segundos"])
                else tempo_na_vaga(linha["entrada"])
            ),
            axis=1
        )

        st.dataframe(
            df[["vaga_id", "entrada", "saida", "Tempo"]],
            use_container_width=True,
            hide_index=True
        )

        finalizadas = df[df["duracao_segundos"].notna()]
        if not finalizadas.empty:
            st.metric(
                "Permanência média",
                formatar_tempo(
                    finalizadas["duracao_segundos"].mean()
                )
            )
    else:
        st.write("Nenhuma permanência registrada.")

    st.divider()
    st.subheader("📋 Histórico de eventos")

    eventos = listar_eventos()
    if eventos:
        st.dataframe(
            pd.DataFrame(eventos),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.write("Nenhum evento registrado.")

    st.caption(
        "Última atualização: " +
        datetime.now().strftime("%H:%M:%S")
    )


historicos()

st.caption("Vaga Inteligente | Protótipo acadêmico")

