#!/bin/bash

# Check if at least one IP address is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 ip1 [ip2 ip3 ...]"
    exit 1
fi

sudo iptables -t nat -F PREROUTING
sudo iptables -t nat -F OUTPUT

CONTAINER_IP="10.0.0.2"
ENDPOINT_IP="$1"

sudo iptables -t nat -A PREROUTING ! -s $CONTAINER_IP -d $ENDPOINT_IP -j DNAT --to-destination $CONTAINER_IP

shift
for ip in "$@"; do    
    sudo ip route add $ip via $CONTAINER_IP
done

echo "200 custom_route" | sudo tee -a /etc/iproute2/rt_tables
sudo ip route add 192.168.0.0/16 dev ens2 table custom_route
ip rule add from $CONTAINER_IP table custom_route

sudo iptables -t nat -A POSTROUTING -j MASQUERADE
