# Building the Application
Notice that Opencraft is hosted in a private repository.
In order to be able to build Opencraft using Ansible, you need to have a ssh-key added to your key manager that has access to the repository.

To do that, execute
```
eval $(ssh-agent)
ssh-add path/to/private/key/with/access
```

## Publisher
For the publisher, simply execute the `docker.sh` script to build it.

To be able to build the _linux/arm64_ architecture, you will need to install Docker Desktop.
Once installed and running, you can check with `docker buildx ls` if a driver is selected that supports the architecture.
This is indicated by the `*` behind the name.  
If this is not the case and you see `desktop-linux` in the list, execute
```
docker buildx create --use desktop-linux
```
This will create a new driver based on Docker Desktop and select it as the default.
This change does not persist across reboots.

## Subscriber
For the subscriber, execute
```
ansible-playbook build_server.yml -v
```
which will then run Ansible locally to build and push the server/subscriber.
