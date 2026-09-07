# EyeAssist Nginx Port 80 Proxy

This phase exposes the existing EyeAssist WebUI fork on standard HTTP port 80 while keeping the application itself bound to port 8080. Nginx proxies only `/` to `http://127.0.0.1:8080`.

Do not publish the RAG (`8100`), Vision (`8200`), Orchestrator (`8300`), or Ollama (`11434`) services through Nginx in this phase.

## Files

- `deploy_staging/nginx/eyeassist.conf`: Nginx site config for EyeAssist WebUI.
- `/etc/nginx/sites-available/eyeassist`: Target host path for the deployed site config.
- `/etc/nginx/sites-enabled/eyeassist`: Enabled symlink for the site config.

## Install Nginx if Missing

Run these commands one at a time on `eyeassist-prod`:

```bash
command -v nginx && nginx -v
```

```bash
sudo apt-get update
```

```bash
sudo apt-get install -y nginx
```

```bash
sudo systemctl enable nginx
```

## Deploy Site Config

Run these commands one at a time from the repo root:

```bash
sudo cp deploy_staging/nginx/eyeassist.conf /etc/nginx/sites-available/eyeassist
```

```bash
sudo ln -sfn /etc/nginx/sites-available/eyeassist /etc/nginx/sites-enabled/eyeassist
```

If the default Nginx site is still enabled and conflicts with the port 80 default server, disable it:

```bash
sudo rm -f /etc/nginx/sites-enabled/default
```

Validate the config:

```bash
sudo nginx -t
```

Reload Nginx:

```bash
sudo systemctl reload nginx
```

## Firewall Guidance

Keep this local-network only. If UFW is enabled, allow port 80 only from the clinic LAN subnet instead of opening it globally. Replace `192.168.1.0/24` with the actual clinic LAN subnet:

```bash
sudo ufw status verbose
```

```bash
sudo ufw allow from 192.168.1.0/24 to any port 80 proto tcp comment 'EyeAssist WebUI LAN HTTP'
```

If a broad HTTP rule already exists, remove it after confirming it is not required for another local service:

```bash
sudo ufw status numbered
```

```bash
sudo ufw delete allow 80/tcp
```

The Nginx site config also denies non-local and non-private source ranges as a second guardrail.

## Verification

Run these commands one at a time:

```bash
sudo nginx -t
```

```bash
systemctl status nginx
```

```bash
curl -I http://localhost
```

```bash
curl -I http://eyeassist-prod
```

Optional hostname check from the server:

```bash
getent hosts eyeassist-prod
```

Optional remote check from a clinic LAN workstation:

```bash
curl -I http://eyeassist-prod
```

## Clinic DNS and DHCP Notes

Create or confirm a DHCP reservation for the EyeAssist host so `eyeassist-prod` keeps a stable LAN IP address.

Add a clinic DNS record or local resolver entry:

- `eyeassist-prod` -> reserved LAN IP
- `eyeassist` -> same reserved LAN IP, either as an A record or CNAME

If DNS is not available during staging, add temporary workstation hosts-file entries that point both names to the reserved LAN IP. Replace `192.168.1.50` with the real IP:

```text
192.168.1.50 eyeassist-prod eyeassist
```

## Rollback

Run these commands one at a time:

```bash
sudo rm -f /etc/nginx/sites-enabled/eyeassist
```

```bash
sudo rm -f /etc/nginx/sites-available/eyeassist
```

If the default site was disabled and should be restored:

```bash
sudo ln -sfn /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
```

Validate the remaining Nginx config:

```bash
sudo nginx -t
```

Reload or stop Nginx:

```bash
sudo systemctl reload nginx
```

If Nginx was installed only for this proxy and is no longer needed:

```bash
sudo systemctl disable --now nginx
```

Remove the UFW LAN rule if it was added:

```bash
sudo ufw status numbered
```

```bash
sudo ufw delete <rule-number>
```
