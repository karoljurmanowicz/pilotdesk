#!/usr/bin/env bash
# PilotDesk – instalacja serwera pośredniczącego (łączenie po ID przez internet).
#
# Uruchom na serwerze z Linuksem (Ubuntu / Debian / Oracle Linux / CentOS / Rocky), jako root:
#   curl -fsSL https://raw.githubusercontent.com/karoljurmanowicz/pilotdesk/main/scripts/install_relay.sh | sudo bash
#
# Skrypt:
#   * instaluje Pythona 3 (jeśli go nie ma),
#   * pobiera pd_relay.py do /opt/pilotdesk-relay i uruchamia go jako usługę systemd (start po restarcie serwera),
#   * otwiera port TCP (domyślnie 47900) w zaporze systemu (ufw / firewalld / iptables),
#   * na końcu wypisuje adres, który trzeba wpisać w PilotDesk.
# Serwer tylko przekazuje zaszyfrowane dane między komputerami – nie zna haseł i nie widzi ekranu.
# Nie zmienia nic w istniejącej stronie internetowej (używa osobnego portu).
set -euo pipefail

PORT="${PORT:-47900}"
DIR=/opt/pilotdesk-relay
SRC="https://raw.githubusercontent.com/karoljurmanowicz/pilotdesk/main/pd_relay.py"

if [ "$(id -u)" -ne 0 ]; then
  echo "Uruchom jako root (sudo)." >&2
  exit 1
fi

echo "==> Python 3"
if ! command -v python3 >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then apt-get update -y && apt-get install -y python3 curl
  elif command -v dnf >/dev/null 2>&1; then dnf install -y python3 curl
  elif command -v yum >/dev/null 2>&1; then yum install -y python3 curl
  else echo "Zainstaluj ręcznie python3 i uruchom skrypt ponownie." >&2; exit 1; fi
fi
python3 --version

echo "==> Pliki serwera w $DIR"
id pilotdesk >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin pilotdesk 2>/dev/null \
  || useradd -r -M -s /sbin/nologin pilotdesk
mkdir -p "$DIR"
curl -fsSL "$SRC" -o "$DIR/pd_relay.py"
chown -R pilotdesk: "$DIR"

echo "==> Usługa systemd pilotdesk-relay"
cat > /etc/systemd/system/pilotdesk-relay.service <<EOF
[Unit]
Description=PilotDesk relay (serwer pośredniczący)
After=network-online.target
Wants=network-online.target

[Service]
User=pilotdesk
WorkingDirectory=$DIR
ExecStart=$(command -v python3) $DIR/pd_relay.py --port $PORT --db $DIR/relay_ids.json
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$DIR
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now pilotdesk-relay
systemctl restart pilotdesk-relay

echo "==> Zapora: port TCP $PORT"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow "$PORT"/tcp
fi
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-port="$PORT"/tcp && firewall-cmd --reload
fi
# obrazy Oracle Cloud (Ubuntu) mają domyślnie regułę REJECT w iptables
if command -v iptables >/dev/null 2>&1 && iptables -S INPUT 2>/dev/null | grep -q -- "-j REJECT"; then
  iptables -C INPUT -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p tcp --dport "$PORT" -j ACCEPT
  if command -v netfilter-persistent >/dev/null 2>&1; then netfilter-persistent save || true; fi
fi

sleep 1
if systemctl is-active --quiet pilotdesk-relay; then
  IP=$(curl -fsS -4 --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
  echo
  echo "======================================================================"
  echo " Serwer pośredniczący PilotDesk działa."
  echo " Adres do wpisania w PilotDesk (Ustawienia -> Serwer pośredniczący):"
  echo
  echo "     $IP:$PORT"
  echo
  echo " Jeśli serwer stoi w chmurze (Oracle, AWS, Azure, Hetzner…), otwórz też"
  echo " port TCP $PORT w panelu dostawcy (Security List / Security Group / Firewall)."
  echo "======================================================================"
else
  echo "Usługa nie wystartowała – zobacz: journalctl -u pilotdesk-relay -n 50" >&2
  exit 1
fi
