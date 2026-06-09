#!/usr/bin/env bash

# ==============================================================================
# WebReel Cloudflare Firewall Hardening Script
# ==============================================================================
# Tac gia: Antigravity AI
# Muc tieu: Chi cho phep Cloudflare va IP tin cay truy cap vao port exposed cua Nginx (3000)
# tren Docker host, ngan chan bypass WAF/DDoS.
# 
# LUU Y: Script nay chi ap dung tren Linux VPS hoac Cloud Server co iptables.
# Khong hoat dong tren moi truong Windows Local/Docker Desktop.
# ==============================================================================

# Ngung script ngay lap tuc neu co loi
set -e

# --- CAU HINH ---
# Cac cong expose cua Docker can bao ve (phan cach bang dau cach)
CF_PORTS="3000"

# Danh sach IP/Subnet tin cay duoc phep truy cap truc tiep (khong qua Cloudflare)
# Vi du: TRUSTED_IPS="1.2.3.4 5.6.7.8/24"
TRUSTED_IPS=""

# URL lay danh sach IP Cloudflare
CF_IPV4_URL="https://www.cloudflare.com/ips-v4"
CF_IPV6_URL="https://www.cloudflare.com/ips-v6"

# Danh sach IP Cloudflare du phong (Static Fallback) trong truong hop loi mang
FALLBACK_CF_IPV4="
173.245.48.0/20
103.21.244.0/22
103.22.200.0/22
103.31.4.0/22
141.101.64.0/18
108.162.192.0/18
190.93.240.0/20
188.114.96.0/20
197.234.240.0/22
198.41.128.0/17
162.158.0.0/15
104.16.0.0/13
104.24.0.0/14
172.64.0.0/13
131.0.72.0/22
"

FALLBACK_CF_IPV6="
2400:cb00::/32
2606:4700::/32
2803:f800::/32
2405:b500::/32
2405:8100::/32
2a06:98c0::/29
2c0f:f248::/32
"

CUSTOM_CHAIN="DOCKER-USER-CLOUDFLARE"

# --- KIEM TRA QUYEN ADMIN ---
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Vui long chay script nay duoi quyen root (sudo)."
    exit 1
fi

# --- CAC HAM TRO GIUP ---

# Lay danh sach IP
fetch_cloudflare_ips() {
    local url=$1
    local fallback=$2
    local ips=""

    if command -v curl >/dev/null 2>&1; then
        ips=$(curl -s -m 10 "$url" || true)
    elif command -v wget >/dev/null 2>&1; then
        ips=$(wget -qO- --timeout=10 "$url" || true)
    fi

    # Neu tai ve trong hoac bi loi, dung fallback
    if [ -z "$ips" ] || echo "$ips" | grep -q "html"; then
        echo "WARNING: Khong the tai danh sach IP tu $url. Dung danh sach du phong." >&2
        echo "$fallback"
    else
        echo "$ips"
    fi
}

# Kich hoat tuong lua
enable_firewall() {
    echo "==> Dang kich hoat tuong lua Cloudflare cho Docker..."

    # 1. Lay danh sach IP Cloudflare
    echo "    Dang lay danh sach IP Cloudflare..."
    local cf_ipv4
    cf_ipv4=$(fetch_cloudflare_ips "$CF_IPV4_URL" "$FALLBACK_CF_IPV4")

    # 2. Cau hinh IPv4 (iptables)
    echo "    Dang thiet lap luat IPv4 (iptables)..."
    
    # Tao custom chain neu chua co
    if ! iptables -L "$CUSTOM_CHAIN" -n >/dev/null 2>&1; then
        iptables -N "$CUSTOM_CHAIN"
    fi

    # Xoa sach cac luat cu trong custom chain
    iptables -F "$CUSTOM_CHAIN"

    # Chen luat nhay tu DOCKER-USER sang CUSTOM_CHAIN neu chua co
    if ! iptables -C DOCKER-USER -j "$CUSTOM_CHAIN" >/dev/null 2>&1; then
        iptables -I DOCKER-USER 1 -j "$CUSTOM_CHAIN"
    fi

    # Cho phep cac ket noi da thiet lap (ESTABLISHED, RELATED) de container truy cap Internet ra ngoai
    iptables -A "$CUSTOM_CHAIN" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT

    # Cho phep loopback interface
    iptables -A "$CUSTOM_CHAIN" -i lo -j ACCEPT

    # Add Cloudflare IPs & Trusted IPs
    for port in $CF_PORTS; do
        echo "    Configuring rules for IPv4 Port: $port"
        
        # Cho phep Cloudflare IPs
        for ip in $cf_ipv4; do
            if [ -n "$ip" ]; then
                iptables -A "$CUSTOM_CHAIN" -p tcp -m conntrack --ctorigdstport "$port" --ctdir ORIGINAL -s "$ip" -j ACCEPT
            fi
        done

        # Cho phep Trusted IPs
        for ip in $TRUSTED_IPS; do
            if [ -n "$ip" ]; then
                iptables -A "$CUSTOM_CHAIN" -p tcp -m conntrack --ctorigdstport "$port" --ctdir ORIGINAL -s "$ip" -j ACCEPT
            fi
        done

        # Drop tat ca cac IP khac co gang truy cap vao port nay
        iptables -A "$CUSTOM_CHAIN" -p tcp -m conntrack --ctorigdstport "$port" --ctdir ORIGINAL -j DROP
    done

    echo "    Da ap dung luat IPv4 thanh cong."

    # 3. Cau hinh IPv6 (ip6tables) neu he thong co ho tro va Docker co ho tro IPv6
    if command -v ip6tables >/dev/null 2>&1 && ip6tables -L DOCKER-USER -n >/dev/null 2>&1; then
        echo "    Dang thiet lap luat IPv6 (ip6tables)..."
        local cf_ipv6
        cf_ipv6=$(fetch_cloudflare_ips "$CF_IPV6_URL" "$FALLBACK_CF_IPV6")

        # Tao custom chain neu chua co
        if ! ip6tables -L "$CUSTOM_CHAIN" -n >/dev/null 2>&1; then
            ip6tables -N "$CUSTOM_CHAIN"
        fi

        # Xoa sach custom chain
        ip6tables -F "$CUSTOM_CHAIN"

        # Nhay tu DOCKER-USER sang CUSTOM_CHAIN
        if ! ip6tables -C DOCKER-USER -j "$CUSTOM_CHAIN" >/dev/null 2>&1; then
            ip6tables -I DOCKER-USER 1 -j "$CUSTOM_CHAIN"
        fi

        # Cho phep ESTABLISHED, RELATED va loopback
        ip6tables -A "$CUSTOM_CHAIN" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
        ip6tables -A "$CUSTOM_CHAIN" -i lo -j ACCEPT

        for port in $CF_PORTS; do
            echo "    Configuring rules for IPv6 Port: $port"
            
            # Cho phep Cloudflare IPv6
            for ip in $cf_ipv6; do
                if [ -n "$ip" ]; then
                    ip6tables -A "$CUSTOM_CHAIN" -p tcp -m conntrack --ctorigdstport "$port" --ctdir ORIGINAL -s "$ip" -j ACCEPT
                fi
            done

            # Drop tat ca cac IP khac co gian truy cap vao port nay qua IPv6
            ip6tables -A "$CUSTOM_CHAIN" -p tcp -m conntrack --ctorigdstport "$port" --ctdir ORIGINAL -j DROP
        done
        echo "    Da ap dung luat IPv6 thanh cong."
    else
        echo "    He thong khong ho tro hoac chua bat IPv6 cho Docker. Bo qua cau hinh IPv6."
    fi

    echo "==> KICH HOAT TUONG LUA THANH CONG."
    echo "    Luu y: Cac luat iptables se bi mat khi reset lai VPS. Ban nen su dung goi 'iptables-persistent' hoac nap script nay luc khoi dong."
}

# Tat tuong lua
disable_firewall() {
    echo "==> Dang go bo tuong lua Cloudflare khoi Docker..."

    # Go bo IPv4
    if iptables -L DOCKER-USER -n >/dev/null 2>&1; then
        if iptables -C DOCKER-USER -j "$CUSTOM_CHAIN" >/dev/null 2>&1; then
            iptables -D DOCKER-USER -j "$CUSTOM_CHAIN"
        fi
    fi

    if iptables -L "$CUSTOM_CHAIN" -n >/dev/null 2>&1; then
        iptables -F "$CUSTOM_CHAIN"
        iptables -X "$CUSTOM_CHAIN"
    fi
    echo "    Da xoa bo cau hinh IPv4."

    # Go bo IPv6
    if command -v ip6tables >/dev/null 2>&1; then
        if ip6tables -L DOCKER-USER -n >/dev/null 2>&1; then
            if ip6tables -C DOCKER-USER -j "$CUSTOM_CHAIN" >/dev/null 2>&1; then
                ip6tables -D DOCKER-USER -j "$CUSTOM_CHAIN"
            fi
        fi

        if ip6tables -L "$CUSTOM_CHAIN" -n >/dev/null 2>&1; then
            ip6tables -F "$CUSTOM_CHAIN"
            ip6tables -X "$CUSTOM_CHAIN"
        fi
        echo "    Da xoa bo cau hinh IPv6."
    fi

    echo "==> GO BO TUONG LUA THANH CONG."
}

# --- CONTROL FLOW ---
case "$1" in
    enable)
        enable_firewall
        ;;
    disable)
        disable_firewall
        ;;
    *)
        echo "Usage: $0 {enable|disable}"
        exit 1
        ;;
esac
