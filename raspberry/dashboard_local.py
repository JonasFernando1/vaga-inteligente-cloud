"""Dashboard Streamlit na rede local (porta 8501)."""
from datetime import datetime
import requests
import streamlit as st

API = "http://127.0.0.1:8000"
st.set_page_config(page_title="Vaga Inteligente | Local", page_icon="🚗", layout="wide")
st.title("🚗 Vaga Inteligente")
st.caption("Painel local do Raspberry Pi 4B · monitoramento das vagas IR e RC522")


def chamar(metodo, rota, **kwargs):
    resposta = requests.request(metodo, API + rota, timeout=6, **kwargs)
    resposta.raise_for_status()
    return resposta.json()


def tempo_atual(entrada):
    if not entrada:
        return "00:00:00"
    try:
        inicio = datetime.fromisoformat(entrada.replace("Z", "+00:00"))
        agora = datetime.now().astimezone()
        if inicio.tzinfo is None:
            inicio = inicio.replace(tzinfo=agora.tzinfo)
        segundos = max(0, int((agora - inicio).total_seconds()))
        horas, resto = divmod(segundos, 3600)
        minutos, segundos = divmod(resto, 60)
        return f"{horas:02d}:{minutos:02d}:{segundos:02d}"
    except (ValueError, TypeError):
        return "--:--:--"


@st.fragment(run_every="2s")
def painel():
    try:
        dados = chamar("GET", "/status")
    except requests.RequestException as erro:
        st.error(f"API indisponível: {erro}")
        return

    vagas = dados["vagas"]
    ocupadas = sum(bool(v["ocupada"]) for v in vagas)
    c1, c2, c3 = st.columns(3)
    c1.metric("Total de vagas", len(vagas))
    c2.metric("Vagas livres", len(vagas) - ocupadas)
    c3.metric("Vagas ocupadas", ocupadas)

    colunas = st.columns(max(1, len(vagas)))
    for coluna, vaga in zip(colunas, vagas):
        with coluna:
            st.subheader(f"Vaga {vaga['id']}")
            if vaga["ocupada"]:
                st.error("🔴 OCUPADA")
                st.metric("Tempo estacionado", tempo_atual(vaga["entrada"]))
            else:
                st.success("🟢 LIVRE")
                st.metric("Tempo estacionado", "00:00:00")

    st.divider()
    cancela = dados["cancela"]
    rfid = dados["rfid"]
    cc, rc = st.columns(2)
    with cc:
        st.subheader("Cancela SG90")
        st.write("Estado comandado:", "ABERTA" if cancela["cancela_aberta"] else "FECHADA")
        st.caption("Posição comandada; não existe sensor que confirme posição física.")
        auto = cancela.get("fechamento_automatico_rfid", {})
        st.write("Fechamento RFID:", auto.get("estado", "indisponível"))
        if auto.get("segundos_restantes") is not None:
            st.write("Contagem:", auto["segundos_restantes"], "segundos")
        if auto.get("modo_bancada_sem_sensor"):
            st.warning("Modo sem ultrassônico: exclusivo para bancada sem veículos ou pessoas.")
        else:
            st.info("Fechamento sem ultrassônico desabilitado.")
        st.write("Obstáculo SIMULADO:", bool(cancela.get("obstaculo_simulado")))
    with rc:
        st.subheader("Cartão RFID")
        st.write("Monitor:", "rodando" if rfid["monitor_ativo"] else "parado")
        st.write("Leitor RC522:", "conectado" if rfid.get("leitor_conectado") else "indisponível")
        if rfid.get("ultimo_erro"):
            st.caption("Último erro: " + str(rfid["ultimo_erro"]))
        leitura = rfid.get("ultima_leitura")
        if leitura:
            st.write("Nome:", leitura["nome"])
            st.write("Status:", leitura["status"])
            st.caption(leitura["mensagem"] + " · " + leitura["horario"])
        else:
            st.caption("Nenhum cartão lido nesta execução.")


painel()
st.divider()
st.subheader("Controle manual (protótipo)")
st.warning("Não acione com pessoas ou veículos na trajetória da haste. O HC-SR04 ainda não foi validado.")
a, b, c, d = st.columns(4)
with a:
    if st.button("⬆️ Abrir", use_container_width=True):
        try:
            r = chamar("POST", "/cancela/abrir")
            (st.success if r.get("sucesso") else st.error)(r.get("mensagem", "Sem resposta"))
        except requests.RequestException as erro:
            st.error(str(erro))
with b:
    if st.button("⬇️ Fechar (teste)", use_container_width=True):
        try:
            r = chamar("POST", "/cancela/fechar")
            (st.success if r.get("sucesso") else st.error)(r.get("mensagem", "Sem resposta"))
        except requests.RequestException as erro:
            st.error(str(erro))
with c:
    if st.button("🚧 Simular obstáculo", use_container_width=True):
        try:
            chamar("POST", "/simulacao/obstaculo", json={"presente": True})
            st.info("Obstáculo simulado habilitado")
        except requests.RequestException as erro:
            st.error(str(erro))
with d:
    if st.button("✅ Limpar simulação", use_container_width=True):
        try:
            chamar("POST", "/simulacao/obstaculo", json={"presente": False})
            st.info("Obstáculo simulado desabilitado")
        except requests.RequestException as erro:
            st.error(str(erro))

with st.expander("Eventos e histórico"):
    try:
        eventos = chamar("GET", "/eventos?limite=25")
        permanencias = chamar("GET", "/permanencias?limite=25")
        st.write("Últimos eventos")
        st.dataframe(eventos, use_container_width=True)
        st.write("Permanências encerradas")
        st.dataframe(permanencias, use_container_width=True)
    except requests.RequestException as erro:
        st.warning(f"Histórico indisponível: {erro}")

st.caption("OLED e HC-SR04 físico: integrações futuras. Os controles do obstáculo nesta tela são apenas simulados.")
