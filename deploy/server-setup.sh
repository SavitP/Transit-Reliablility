#!/usr/bin/env bash
# One-time setup for a fresh Ubuntu 24.04 server. Run as root, e.g.:
#   ssh root@YOUR_SERVER_IP 'bash -s' < deploy/server-setup.sh            (Hetzner, DigitalOcean)
#   ssh ubuntu@YOUR_SERVER_IP 'sudo bash -s' < deploy/server-setup.sh     (AWS Lightsail / EC2)
#
# What it does:
#   1. Creates a normal user "transit" (with your SSH key) so you stop logging in as root.
#   2. Turns off password logins over SSH (keys only) and root login.
#   3. Firewall: allow only SSH (22), HTTP (80) and HTTPS (443).
#   4. Automatic security updates.
#   5. A 2 GB swap file (spare memory on disk) so a memory spike slows things down instead of crashing.
#   6. Installs Docker from Docker's official package source, with log size limits.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "Run this as root (or with sudo)."; exit 1; fi
# Find the SSH key you log in with: root's (most providers) or the sudo user's (AWS's "ubuntu").
KEYS=/root/.ssh/authorized_keys
if [[ ! -s $KEYS && -n ${SUDO_USER:-} ]]; then
    KEYS=/home/$SUDO_USER/.ssh/authorized_keys
fi
if [[ ! -s $KEYS ]]; then
    echo "No SSH key found. Add your key when creating the server first,"
    echo "otherwise turning off password login would lock you out. Stopping."
    exit 1
fi

echo "==> Updating packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -y -q
apt-get install -y -q ca-certificates curl git ufw unattended-upgrades

echo "==> Creating user 'transit' with your SSH key"
if ! id transit >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" transit
    usermod -aG sudo transit
fi
install -d -m 700 -o transit -g transit /home/transit/.ssh
install -m 600 -o transit -g transit "$KEYS" /home/transit/.ssh/authorized_keys
# Let "transit" use sudo without a password (it has none; it logs in with a key).
echo "transit ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/transit
chmod 440 /etc/sudoers.d/transit

echo "==> SSH: keys only, no root login"
cat > /etc/ssh/sshd_config.d/10-hardening.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
CONF
sshd -t && systemctl reload ssh

echo "==> Firewall"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

echo "==> Automatic security updates"
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> 2 GB swap file"
if ! swapon --show | grep -q /swapfile; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

echo "==> Docker (official package source)"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
apt-get update -q
apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
# Without limits, container logs grow until the disk is full. Keep 3 files of 10 MB each.
cat > /etc/docker/daemon.json <<'JSON'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
JSON
systemctl restart docker
usermod -aG docker transit

echo
echo "Done. From now on log in as:  ssh transit@$(curl -s -4 https://ifconfig.me || echo YOUR_SERVER_IP)"
