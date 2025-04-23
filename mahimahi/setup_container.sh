iptables -t nat -A POSTROUTING -d 192.168.192.3 -j MASQUERADE

sysctl -w net.ipv4.conf.ingress.send_redirects=0
sysctl -w net.ipv4.conf.ingress.accept_redirects=0

sysctl -w net.ipv4.conf.all.send_redirects=0
sysctl -w net.ipv4.conf.all.accept_redirects=0

while :
do
  sleep 10
done
