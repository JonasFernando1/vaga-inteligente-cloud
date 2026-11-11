# 🚗 Vaga Inteligente — Raspberry Pi 4B + Streamlit

Projeto de estacionamento inteligente com **duas vagas**, leitores de presença IR,
cartão **RFID RC522**, cancela com **servo SG90**, **FastAPI**, **SQLite** e
painéis Streamlit local e online.

> **Importante:** este repositório reúne o ZIP original do dashboard **online** e
> uma versão consolidada/reconstruída dos scripts do Raspberry com base nas
> integrações anteriores. Antes de atualizar uma instalação funcionando, faça
> backup e teste cada componente. Não contém banco de dados operacional nem
> credenciais.

## Estrutura

```text
vaga-inteligente-cloud-main/
├── dashboard.py               # Streamlit Cloud: consulta Supabase (original preservado)
├── requirements.txt           # Dependências do dashboard online (original)
├── .streamlit/
│   └── secrets.toml.example   # Exemplo, NÃO contém credenciais
├── .gitignore                 # Ignora banco, senhas, venv e backups
├── raspberry/
│   ├── api.py                 # FastAPI localhost:8000
│   ├── banco.py               # SQLite + vagas/eventos/permanências/cartões
│   ├── controlador.py         # Cancela física; comandos V4 e temporizador de bancada
│   ├── servo_cancela.py       # SG90 GPIO18; 850 µs abre e 1550 µs fecha
│   ├── leitor_rfid.py         # RC522; reconexão automática em falha no boot
│   ├── sensores_ir.py         # IR BCM17 e BCM27 (LOW = ocupado)
│   ├── sensor_ultrassonico.py # Contrato provisório; sensor ainda NÃO validado
│   ├── dashboard_local.py     # Streamlit local, porta 8501
│   ├── cadastrar_cartao.py    # Cadastro sem deixar UIDs no Git
│   ├── requirements.txt
│   ├── .env.example
│   ├── systemd/
│   │   ├── vaga-api.service
│   │   └── vaga-dashboard.service
│   ├── scripts/
│   │   ├── atualizar_raspberry.sh
│   │   └── diagnostico.sh
│   └── tests/
│       └── test_core.py
└── README.md
```

## O que funciona e o que ainda depende de hardware

| Funcionalidade | Estado do código |
|---|---|
| Monitorar vagas pelos sensores IR | Implementado; validar polaridade e pinos na montagem |
| Ler RFID, consultar cartão autorizado no SQLite | Implementado |
| Recuperar leitor RFID após erro de inicialização | Implementado com retentativa a cada 3 s |
| Abrir cancela pelo RFID / dashboard | Implementado; exige teste no SG90 físico |
| Fechar manualmente no modo de bancada | Implementado; bloqueado por padrão |
| Agendar fechamento RFID em 10 s | Implementado somente no modo de bancada |
| Confirmar ausência de carro por ultrassom | **Pendente; HC-SR04 ainda não foi validado** |
| Fechamento físico seguro para trânsito real | **Não implementado** |
| Dashboard online consultando Supabase | Implementado (`dashboard.py`); tabelas em `supabase/schema.sql` |
| Publicar vagas e status no Supabase | Implementado (`raspberry/sincronizador.py`, serviço `vaga-sync`) |
| Abrir/fechar a cancela pelo dashboard online | Implementado com login; passa pelas mesmas travas da API local |

### Segurança da cancela

O módulo `sensor_ultrassonico.py` **não simula um sensor funcionando**:
retorna `funcionando=False`, `obstaculo=None` e `passagem_livre=False`.
O modo sem sensor usa duas variáveis e é destinado **exclusivamente a ensaios
supervisionados com a maquete vazia**, sem pessoas ou veículos na trajetória:

- `VAGA_FECHAMENTO_TESTE=1` — habilita apenas o fechamento manual de bancada.
- `VAGA_AUTO_SEM_SENSOR_BANCADA=1` — junto com a primeira variável, habilita o
  fechamento RFID em 10 segundos em bancada, por no máximo 15 minutos após a
  inicialização do processo.

**Não mantenha essas variáveis habilitadas no boot automático.** Um reinício
reinicia a janela de bancada. Sem sensor confiável, não use a cancela para
circulação de veículos. Um único HC-SR04 não substitui um sistema anticolisão
adequado.

O SG90 não tem feedback de posição: a API informa a **posição comandada**, não
que a haste chegou de fato ao destino. Use alimentação 5 V regulada separada
para o servo, com terra comum ao Raspberry, e proteja a trajetória da haste.

## Dashboard online (Supabase + Streamlit Cloud)

```text
Raspberry: api.py ◀─HTTP─ sincronizador.py ──▶ Supabase ◀── dashboard.py (Streamlit Cloud)
                          (vaga-sync)          status_vagas, status_sistema, comandos_cancela
```

- O **sincronizador** é um processo separado: lê a API local (`/vagas` e
  `/cancela/status`), envia ao Supabase e manda um sinal de vida a cada 10 s.
  Não usa GPIO nem o SQLite; se a internet cair, sensores e cancela seguem
  funcionando.
- **Cancela pelo dashboard:** o usuário logado cria um comando em
  `comandos_cancela`; o sincronizador o busca (a cada 1,5 s) e chama
  `POST /cancela/abrir` ou `/cancela/fechar` na API local. Valem as mesmas
  travas da API: **fechar continua bloqueado sem `VAGA_FECHAMENTO_TESTE=1`**.
  Comando com mais de 20 s expira no servidor, para que um clique antigo não
  mova a cancela quando o Pi voltar a ter internet.
- Chaves: o dashboard usa só a chave **pública** (anon/publishable), que
  apenas lê; o login libera criar comandos. A chave **secreta** fica somente
  no Raspberry, em `.env.supabase`.

### 1. Supabase (uma vez)

1. **SQL Editor → New query**: cole `supabase/schema.sql` e rode.
2. **Authentication → Users → Add user**: crie o usuário (e-mail e senha) que
   vai controlar a cancela. Desligue o cadastro público em
   **Authentication → Sign In / Providers → Allow new users to sign up**, para
   que ninguém crie uma conta sozinho.
3. **Project Settings → API Keys**: anote a URL, a chave pública e a secreta.

### 2. Testar no PC, sem o Raspberry

```bash
pip install streamlit requests
cp raspberry/.env.supabase.example raspberry/.env.supabase          # preencher URL + chave secreta
cp .streamlit/secrets.toml.example .streamlit/secrets.toml  # preencher URL + chave pública

python simulador.py                    # terminal 1: API falsa em 127.0.0.1:8000
python raspberry/sincronizador.py      # terminal 2: mesma ponte que roda no Pi
streamlit run dashboard.py             # terminal 3: dashboard em localhost:8501
```

No terminal do simulador, digite `1` ou `2` + Enter para trocar a vaga.
`python simulador.py --sem-fechamento` imita o Pi com o fechamento bloqueado.

### 3. Publicar o dashboard

[share.streamlit.io](https://share.streamlit.io) → **Create app** → este
repositório, branch `main`, arquivo `dashboard.py`. Em **Advanced settings →
Secrets**, cole o conteúdo do seu `.streamlit/secrets.toml`.

### 4. Ligar no Raspberry

```bash
bash raspberry/scripts/atualizar_raspberry.sh     # copia sincronizador.py
cp raspberry/.env.supabase.example ~/vaga-inteligente/.env.supabase
nano ~/vaga-inteligente/.env.supabase                 # URL + chave secreta
chmod 600 ~/vaga-inteligente/.env.supabase
sudo cp raspberry/systemd/vaga-sync.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vaga-sync.service
sudo journalctl -u vaga-sync.service -f           # ver o que ele está enviando
```

## Publicar no GitHub

Descompacte o ZIP e use, no diretório raiz:

```bash
git init
git add .
git commit -m "feat: organize smart parking Raspberry Pi and cloud dashboard"
git branch -M main
git remote add origin https://github.com/SEU-USUARIO/SEU-REPOSITORIO.git
git push -u origin main
```

Se seu repositório já existe, prefira substituir os arquivos e executar apenas
`git add .`, `git commit ...` e `git push` dentro da cópia clonada. **Não execute
`git init` novamente se já estiver em um clone.**

O arquivo `dashboard.py` e o `requirements.txt` da **raiz** são os do Streamlit
Cloud. Os serviços locais usam os scripts dentro de `raspberry/`.

## Atualizar o Raspberry existente sem apagar os dados

No Raspberry, com o repositório clonado, execute:

```bash
cd ~/vaga-inteligente-cloud-main
bash raspberry/scripts/atualizar_raspberry.sh
```

O script copia os `.py` de `raspberry/` para `~/vaga-inteligente/`, faz backup
dos `.py` anteriores e reinicia a API **se ela estava ativa**. Ele **não copia
nem altera** `dados/estacionamento.db`, `venv/`, cartões cadastrados ou arquivos
de ambiente. O seu `dashboard.py` antigo no Pi é preservado para não quebrar a
interface que já funciona. Se desejar testar o novo dashboard local, use os
comandos da seção seguinte.

**Atenção à compatibilidade:** `banco.py`, `api.py` e `sensores_ir.py` foram
reconstruídos a partir da arquitetura descrita, pois não estavam no ZIP
original. Confirme o esquema SQLite existente e faça backup do banco antes de
atualizar uma instalação real. O script de atualização não substitui o banco.

## Instalação nova do ambiente local (Raspberry Pi OS/Debian)

No Raspberry Pi 4B:

```bash
sudo apt update
sudo apt install -y python3-venv python3-lgpio python3-gpiozero python3-spidev
mkdir -p ~/vaga-inteligente
cd ~/vaga-inteligente
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r ~/vaga-inteligente-cloud-main/raspberry/requirements.txt
bash ~/vaga-inteligente-cloud-main/raspberry/scripts/atualizar_raspberry.sh
```

Confira se SPI está habilitado (via `sudo raspi-config`, **Interface Options → SPI**)
e se `/dev/spidev0.0` existe. Os pacotes do sistema para GPIO podem variar com
a versão do Raspberry Pi OS. Caso já tenha um `venv` funcional, **mantenha-o**.

Para instalar os serviços novos **apenas em uma instalação nova** (em um Pi
existente, verifique/guarde os seus units atuais antes de sobrescrever):

```bash
sudo cp ~/vaga-inteligente-cloud-main/raspberry/systemd/vaga-api.service /etc/systemd/system/
sudo cp ~/vaga-inteligente-cloud-main/raspberry/systemd/vaga-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vaga-api.service vaga-dashboard.service
```

Dashboard na rede Wi-Fi local: **`http://vaga.local:8501`** se mDNS estiver
funcionando, ou `http://IP-DO-RASPBERRY:8501`. API em
`http://127.0.0.1:8000/status` **somente dentro do Raspberry**.

O dashboard exposto na porta 8501 não possui autenticação própria para os
botões físicos: utilize **somente rede local confiável**, sem encaminhamento de
portas para a internet.

### Verificar RFID após reboot

```bash
sudo systemctl status vaga-api.service --no-pager
curl -s http://127.0.0.1:8000/rfid/status
sudo journalctl -u vaga-api.service -b -n 80 --no-pager
ls -l /dev/spidev*
vcgencmd get_throttled
```

Na rota `/rfid/status`, `monitor_ativo=true` significa que o processo de leitura
está rodando; `leitor_conectado=true` significa que o RC522 foi inicializado.
Isso **não garante** que a antena esteja lendo cartões: confira a `ultima_leitura`
após aproximar um cartão e observe `ultimo_erro`. Falhas transitórias passam a
ser tentadas novamente em 3 segundos, mas problemas elétricos ou SPI desligado
precisam de correção física/configuração.

### Cadastrar cartão sem gravar UIDs no código

```bash
cd ~/vaga-inteligente
source venv/bin/activate
python cadastrar_cartao.py 123456789 "Cartão de teste"
python cadastrar_cartao.py 123456789 "Cartão bloqueado" --negar
```

Substitua `123456789` pelo UID real. O cadastro fica somente no SQLite local.

## Hardware previsto

| Componente | GPIO (BCM) | Observação |
|---|---|---|
| IR vaga 1 | 17 | LOW = ocupada |
| IR vaga 2 | 27 | LOW = ocupada |
| Servo SG90 | 18 | 850 µs = aberto; 1550 µs = fechado |
| RC522 SDA/SS | 8 | SPI CE0 |
| RC522 SCK / MOSI / MISO | 11 / 10 / 9 | SPI |
| RC522 RST | 25 | Alimentar RC522 em **3,3 V** |
| HC-SR04 TRIG / ECHO | 23 / 24 | ECHO exige conversão 5 V → 3,3 V; leitura pendente |
| OLED SDA / SCL | 2 / 3 | I²C; integração pendente |

## Testes offline

```bash
cd raspberry
python3 -m unittest discover -s tests -v
python3 -m compileall -q .
```

Esses testes substituem o driver físico por objetos simulados e **não testam**
o SG90, o RC522 nem o ultrassom no hardware real.
