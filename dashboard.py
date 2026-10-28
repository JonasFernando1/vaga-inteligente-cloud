
import streamlit as st
import requests
from datetime import datetime

st.set_page_config(
    page_title="Vaga Inteligente",
    page_icon="🚗",
    layout="wide"
)

URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_ANON_KEY"]

@st.cache_data(ttl=2)
def buscar_vagas():
    resposta = requests.get(
        f"{URL}/rest/v1/status_vagas",
        params={
            "select": "vaga_id,ocupada,entrada,atualizado_em",
            "order": "vaga_id.asc"
        },
        headers={
            "apikey": KEY,
            "Authorization": f"Bearer {KEY}"
        },
        timeout=10
    )
    resposta.raise_for_status()
    return resposta.json()


def tempo_permanencia(entrada):
    if not entrada:
        return "00:00:00"

    inicio = datetime.fromisoformat(
        entrada.replace("Z", "+00:00")
    )
    agora = datetime.now().astimezone()

    segundos = max(
        0, int((agora - inicio).total_seconds())
    )

    horas, resto = divmod(segundos, 3600)
    minutos, segundos = divmod(resto, 60)

    return f"{horas:02d}:{minutos:02d}:{segundos:02d}"


st.title("🚗 Vaga Inteligente")
st.caption("Monitoramento online - Raspberry Pi 4B")

@st.fragment(run_every="5s")
def monitoramento():
    try:
        vagas = buscar_vagas()
    except Exception as erro:
        st.error(f"Falha de comunicação: {erro}")
        return

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

    st.divider()
    st.caption("Dados recebidos do banco online.")

monitoramento()
