"""Display OLED SSD1306 (I2C 0x3C) da Vaga Inteligente.

Programa separado (vaga-display.service): só LÊ a API local e desenha.
Não usa os GPIOs dos sensores nem o banco; se a API cair, mostra o aviso
e tenta de novo.

Tela normal:                    Depois de um cartão (5 s):
  +----------------------+        +----------------------+
  | LIVRES  1/2          |        | LIBERADO             |
  | V1 OCUPADA  V2 LIVRE |        | Cartao 2             |
  | Cancela FECHADA 17:42|        | Acesso autorizado    |
  +----------------------+        +----------------------+

Funciona com as duas versões da API (vagas em /vagas ou /sensores/status;
cancela em /cancela/status ou /status).

Configuração (variáveis de ambiente):
  VAGA_API      padrão http://127.0.0.1:8000
  OLED_ALTURA   64 (padrão) ou 32
  OLED_ENDERECO padrão 0x3C
  OLED_TESTE    caminho .png: desenha num display falso e salva a imagem
                (para testar no PC, sem o display)
"""
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import requests
from PIL import ImageFont

log = logging.getLogger("display")

API = os.environ.get("VAGA_API", "http://127.0.0.1:8000").rstrip("/")
ALTURA = int(os.environ.get("OLED_ALTURA", "64"))
ENDERECO = int(os.environ.get("OLED_ENDERECO", "0x3C"), 16)
INTERVALO = 0.5         # s entre atualizações da tela
TEMPO_CARTAO = 5.0      # s mostrando o resultado de um cartão
TIMEOUT = 2

TITULO_CARTAO = {
    "AUTORIZADO": "LIBERADO",
    "NEGADO": "NEGADO",
    "LOTADO": "LOTADO",
    "FALHA_ABERTURA": "FALHA",
}

FONTES_TTF = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arialbd.ttf",  # só para o teste no PC
]


def fonte(tamanho):
    for caminho in FONTES_TTF:
        if Path(caminho).exists():
            return ImageFont.truetype(caminho, tamanho)
    return ImageFont.load_default()


def criar_display():
    teste = os.environ.get("OLED_TESTE")
    if teste:
        from luma.core.device import dummy
        return dummy(width=128, height=ALTURA, mode="1")
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306
    return ssd1306(i2c(port=1, address=ENDERECO), width=128, height=ALTURA)


# -- leitura da API (nova ou antiga) ---------------------------------------
def get_opcional(rota):
    r = requests.get(API + rota, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def ler_estado():
    vagas = get_opcional("/vagas")
    if vagas is None:
        vagas = requests.get(API + "/sensores/status", timeout=TIMEOUT).json()["vagas"]
    cancela = get_opcional("/cancela/status")
    if cancela is None:
        status = get_opcional("/status") or {}
        cancela = status.get("cancela", status)
    rfid = get_opcional("/rfid/status") or {}
    return vagas, cancela, rfid.get("ultima_leitura")


# -- desenho ----------------------------------------------------------------
def cortar(desenho, texto, fonte_, largura):
    """Corta o texto com '...' para caber na largura."""
    if desenho.textlength(texto, font=fonte_) <= largura:
        return texto
    while texto and desenho.textlength(texto + "...", font=fonte_) > largura:
        texto = texto[:-1]
    return texto + "..."


def tela_normal(d, vagas, cancela, f):
    livres = sum(not v["ocupada"] for v in vagas)
    aberta = cancela.get("cancela_aberta")
    pos = "--" if aberta is None else ("ABERTA" if aberta else "FECHADA")
    hora = datetime.now().strftime("%H:%M")
    estado_vagas = "  ".join(
        f"V{v['id']} {'OCUP.' if v['ocupada'] else 'LIVRE'}" for v in vagas)

    if ALTURA >= 64:
        texto_livres = "LOTADO" if livres == 0 else f"LIVRES {livres}/{len(vagas)}"
        d.text((0, 0), texto_livres, font=f["grande"], fill="white")
        d.text((0, 26), cortar(d, estado_vagas, f["pequena"], 128), font=f["pequena"], fill="white")
        d.line((0, 42, 127, 42), fill="white")
        d.text((0, 48), f"Cancela {pos}", font=f["pequena"], fill="white")
        d.text((128 - d.textlength(hora, font=f["pequena"]), 48), hora,
               font=f["pequena"], fill="white")
    else:
        topo = "LOTADO" if livres == 0 else f"Livres {livres}/{len(vagas)}"
        if aberta is not None:
            topo += "  " + ("ABERTA" if aberta else "FECHADA")
        d.text((0, 0), topo, font=f["pequena"], fill="white")
        d.text((0, 17), cortar(d, estado_vagas, f["pequena"], 128), font=f["pequena"], fill="white")


def tela_cartao(d, leitura, f):
    titulo = TITULO_CARTAO.get(leitura.get("status"), leitura.get("status") or "?")
    nome = leitura.get("nome") or "Desconhecido"
    mensagem = (leitura.get("mensagem") or "").split(";")[0]
    if ALTURA >= 64:
        d.text((0, 0), titulo, font=f["grande"], fill="white")
        d.text((0, 28), cortar(d, nome, f["pequena"], 128), font=f["pequena"], fill="white")
        d.text((0, 46), cortar(d, mensagem, f["mini"], 128), font=f["mini"], fill="white")
    else:
        d.text((0, 0), titulo, font=f["pequena"], fill="white")
        d.text((0, 17), cortar(d, nome, f["pequena"], 128), font=f["pequena"], fill="white")


def tela_erro(d, f):
    d.text((0, 0), "Sem conexao", font=f["pequena"], fill="white")
    d.text((0, 17), "com o sistema", font=f["pequena"], fill="white")
    if ALTURA >= 64:
        d.text((0, 40), "Tentando de novo...", font=f["mini"], fill="white")


def main():
    from luma.core.render import canvas

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    display = criar_display()
    fontes = {"grande": fonte(20), "pequena": fonte(13), "mini": fonte(10)}
    teste = os.environ.get("OLED_TESTE")

    cartao_visto = None      # horário da última leitura já conhecida
    mostrar_cartao_ate = 0.0
    leitura_atual = None
    primeira = True
    estava_com_erro = False
    log.info("Display iniciado (128x%d, API %s)", ALTURA, API)

    while True:
        try:
            vagas, cancela, leitura = ler_estado()
            if estava_com_erro:
                log.info("API voltou")
            estava_com_erro = False
            horario = leitura.get("horario") if leitura else None
            if horario != cartao_visto:
                # Na primeira volta só memoriza: não mostra cartão antigo.
                if not primeira and leitura:
                    leitura_atual = leitura
                    mostrar_cartao_ate = time.monotonic() + TEMPO_CARTAO
                cartao_visto = horario
            primeira = False
            with canvas(display) as d:
                if time.monotonic() < mostrar_cartao_ate and leitura_atual:
                    tela_cartao(d, leitura_atual, fontes)
                else:
                    tela_normal(d, vagas, cancela, fontes)
        except (requests.RequestException, KeyError, TypeError, ValueError) as erro:
            if not estava_com_erro:
                log.warning("Não consegui ler a API: %s", erro)
            estava_com_erro = True
            with canvas(display) as d:
                tela_erro(d, fontes)

        if teste:
            display.image.save(teste)
            log.info("Imagem salva em %s", teste)
            if not estava_com_erro and leitura:
                with canvas(display) as d:
                    tela_cartao(d, leitura, fontes)
                caminho = teste.replace(".png", "-cartao.png")
                display.image.save(caminho)
                log.info("Imagem salva em %s", caminho)
            return
        time.sleep(INTERVALO)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
