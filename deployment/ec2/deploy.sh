#!/usr/bin/env bash
# ==============================================================================
# CampusCare EC2 Automated Deployment Script
# Supports: Amazon Linux 2023, Amazon Linux 2, Ubuntu 22.04 / 24.04 LTS
# ==============================================================================

set -euo pipefail

echo "=================================================="
echo " Starting CampusCare Frontend Deployment on EC2"
echo "=================================================="

# 1. Detect OS and install Nginx
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    OS="unknown"
fi

echo "[1/5] Detected Operating System: $OS"

if [ "$OS" = "amzn" ] || [ "$OS" = "fedora" ] || [ "$OS" = "rhel" ]; then
    echo "Updating system and installing nginx on RPM-based system..."
    sudo dnf update -y || sudo yum update -y
    sudo dnf install -y nginx || sudo yum install -y nginx
elif [ "$OS" = "ubuntu" ] || [ "$OS" = "debian" ]; then
    echo "Updating system and installing nginx on Debian/Ubuntu..."
    sudo apt-get update -y
    sudo apt-get install -y nginx
else
    echo "Unsupported OS: $OS. Please install nginx manually."
    exit 1
fi

# 2. Prepare web root directory
WEB_ROOT="/var/www/campuscare/frontend"
echo "[2/5] Setting up target web directory: $WEB_ROOT"
sudo mkdir -p "$WEB_ROOT"

# 3. Copy frontend files from repo to web root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "[3/5] Copying frontend assets from $REPO_ROOT/frontend to $WEB_ROOT..."
sudo cp -r "$REPO_ROOT/frontend/"* "$WEB_ROOT/"
sudo chown -R nginx:nginx "$WEB_ROOT" 2>/dev/null || sudo chown -R www-data:www-data "$WEB_ROOT" 2>/dev/null || true
sudo chmod -R 755 "$WEB_ROOT"

# 4. Configure Nginx
echo "[4/5] Deploying Nginx site configuration..."
if [ -d /etc/nginx/conf.d ]; then
    sudo cp "$SCRIPT_DIR/nginx.conf" /etc/nginx/conf.d/campuscare.conf
    # Remove default welcome page if exists
    sudo rm -f /etc/nginx/conf.d/default.conf 2>/dev/null || true
elif [ -d /etc/nginx/sites-available ]; then
    sudo cp "$SCRIPT_DIR/nginx.conf" /etc/nginx/sites-available/campuscare
    sudo ln -sf /etc/nginx/sites-available/campuscare /etc/nginx/sites-enabled/
    sudo rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
fi

# Test Nginx syntax
sudo nginx -t

# 5. Enable and start Nginx service
echo "[5/5] Starting and enabling Nginx service..."
sudo systemctl enable nginx
sudo systemctl restart nginx

# 6. Retrieve Public IP if available on EC2 metadata
PUBLIC_IP=$(curl -s --connect-timeout 2 http://169.254.169.254/latest/meta-data/public-ipv4 || hostname -I | awk '{print $1}')

echo "=================================================="
echo " ✓ CampusCare Successfully Deployed on Amazon EC2!"
echo "=================================================="
echo " Frontend URL: http://$PUBLIC_IP"
echo ""
echo " Next Steps:"
echo " 1. Open http://$PUBLIC_IP in your browser."
echo " 2. Ensure your EC2 Security Group permits Inbound HTTP on Port 80."
echo " 3. In the top navbar, click the endpoint badge to configure your"
echo "    AWS Lambda Function URL for end-to-end cloud processing."
echo "=================================================="
