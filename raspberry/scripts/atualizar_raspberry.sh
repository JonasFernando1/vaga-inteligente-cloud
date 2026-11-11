#!/usr/bin/env bash
# Execute na pasta do repositorio clonado: bash raspberry/scripts/atualizar_raspberry.sh
# Faz backup dos scripts existentes; nao sobrescreve dados/ nem venv/.
set -euo pipefail
ORIGEM="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESTINO="${1:-$HOME/vaga-inteligente}"
DATA="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$DESTINO" "$DESTINO/backups/codigo_$DATA"

if systemctl is-active --quiet vaga-api.service; then
    sudo systemctl stop vaga-api.service
    LIGADA=1
else
    LIGADA=0
fi

restaurar_servico() {
    if [ "$LIGADA" -eq 1 ]; then
        sudo systemctl start vaga-api.service || true
    fi
}
trap restaurar_servico EXIT

for origem in "$ORIGEM"/*.py; do
    base="$(basename "$origem")"
    if [ -f "$DESTINO/$base" ]; then
        cp "$DESTINO/$base" "$DESTINO/backups/codigo_$DATA/$base"
    fi
    cp "$origem" "$DESTINO/$base"
done

if [ -x "$DESTINO/venv/bin/python" ]; then
    "$DESTINO/venv/bin/python" -m compileall -q "$DESTINO"/*.py
else
    python3 -m compileall -q "$DESTINO"/*.py
    echo "AVISO: venv nao encontrado. Instale as dependencias antes de iniciar a API."
fi

echo "Atualizado: $DESTINO"
echo "Backup: $DESTINO/backups/codigo_$DATA"
echo "Banco SQLite, cartoes, .env e venv preservados."
