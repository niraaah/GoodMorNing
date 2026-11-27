#!/bin/sh
set -eu
# This container has no application or host mounts. Its only privileged action
# is installing namespace-local firewall rules before dropping every capability.
iptables -P INPUT DROP
iptables -P OUTPUT DROP
iptables -P FORWARD DROP
ip6tables -P INPUT DROP
ip6tables -P OUTPUT DROP
ip6tables -P FORWARD DROP
iptables -F INPUT
iptables -F OUTPUT
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -i lo -s 127.0.0.1/32 -j ACCEPT
iptables -A OUTPUT -o lo -d 127.0.0.1/32 -j ACCEPT
case "$PROFILE" in
  search)
    iptables -A INPUT -p tcp --dport 8788 -j ACCEPT
    iptables -A OUTPUT -d 172.30.74.10 -p tcp --dport 5432 -j ACCEPT
    iptables -A OUTPUT -d 172.30.74.4 -p tcp --dport 8790 -j ACCEPT
    iptables -A OUTPUT -d 172.30.74.2 -p tcp --dport 8080 -j ACCEPT
    ;;
  crawler)
    iptables -A INPUT -s 172.30.74.3 -p tcp --dport 8790 -j ACCEPT
    iptables -A OUTPUT -d 172.30.74.2 -p tcp --dport 8080 -j ACCEPT
    ;;
  gateway)
    iptables -A INPUT -s 172.30.74.3 -p tcp --dport 8080 -j ACCEPT
    iptables -A INPUT -s 172.30.74.4 -p tcp --dport 8080 -j ACCEPT
    # Only the gateway may resolve public names via Docker's embedded resolver.
    iptables -A OUTPUT -d 127.0.0.11 -j ACCEPT
    for range in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.0.0.0/24 192.0.2.0/24 192.168.0.0/16 198.18.0.0/15 198.51.100.0/24 203.0.113.0/24 224.0.0.0/4 240.0.0.0/4; do
      iptables -A OUTPUT -d "$range" -j REJECT
    done
    iptables -A OUTPUT -p tcp --dport 443 -j ACCEPT
    ;;
  *) exit 1 ;;
esac
touch /run/firewall-ready
exec setpriv --reuid=65534 --regid=65534 --clear-groups --bounding-set=-all --inh-caps=-all --ambient-caps=-all sleep infinity
