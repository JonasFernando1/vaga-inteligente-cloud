#!/usr/bin/env bash
set +e
printf '\n=== SERVICOS ===\n'
systemctl is-enabled vaga-api.service vaga-dashboard.service
systemctl is-active vaga-api.service vaga-dashboard.service
printf '\n=== RFID ===\n'
curl -sS --max-time 3 http://127.0.0.1:8000/rfid/status
printf '\n\n=== SPI ===\n'
ls -l /dev/spidev* 2>&1
printf '\n=== ENERGIA ===\n'
vcgencmd get_throttled 2>&1
printf '\n=== LOGS API (30 linhas) ===\n'
sudo journalctl -u vaga-api.service -b -n 30 --no-pager
