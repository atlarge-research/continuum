# Continuum
Software versions tested:

- Python 3.8.10
- Ansible 2.13.6

### Part 1: Install the framework
We start by installing all requirements for the Continuum framework.
We assume the operating system is Ubuntu 20.04, either natively or via a VM.
Ubuntu 22.04 should also work, but commands and packages might slightly differ.

```bash
# 1. Install the Continuum framework
mkdir ~/.ssh
touch ~/.ssh/known_hosts

git clone https://github.com/atlarge-research/continuum.git
cd continuum

# 2. Install Python and some packages, including Ansible
sudo apt install python3 python3-pip
pip3 install -r requirements.txt

# 3. Edit the Ansible configuration as follows on Ubuntu 20.04:
# Under `[defaults]`, add `callback_enabled = profile_tasks`
# Under `[defaults]`, add `command_warnings = False`
# For Ubuntu 22.04, add just the following: callbacks_enabled=profile_tasks
sudo vim /etc/ansible/ansible.cfg
```

### Part 2: Use the framework
```bash
cd continuum

# Add your AWS credentials
vim configuration/kube_opencraft/vm1_setup.cfg

# Run Continuum
python3 continuum.py configuration/kube_opencraft/vm1_setup.cfg

# Continuum saves its files in ${HOME}/.continuum
# On execution, it deletes any previously created resources
# In this case, it tries to delete any previously created AWS resources
# If you are done with Continuum, you need to delete your resources by hand:
cd ${HOME}/.continuum/images
terraform destroy -auto-approve
```