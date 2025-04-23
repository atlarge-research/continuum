ip route add 192.168.192.3 via 10.0.0.2
echo "200 custom_route" | sudo tee -a /etc/iproute2/rt_tables
ip route add default via 192.168.1.100 table custom_route
ip rule add from 10.0.0.2 table custom_route