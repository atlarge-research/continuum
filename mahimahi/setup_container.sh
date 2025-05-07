CONTAINER_IP="10.0.0.2"

sudo iptables -t nat -A PREROUTING -d $CONTAINER_IP -j DNAT --to-destination 10.0.0.1
sudo iptables -t nat -A POSTROUTING -j MASQUERADE

while :
do
  sleep 10
done
