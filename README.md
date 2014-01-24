puppet_test
===========

Functional testing of Puppet modules
# Installation and configuration

Make sure SELinux is disabled

To disable SELinux :
1) Change configuration and Reboot
/etc/selinux/config
```
SELINUX=disabled
```

2) Make sure forwarding is enabled:
```
sysctl net.ipv4.ip_forward=1
```

3) Install necessary components and build basic docker image
```
cd ./docker
./prepare_docker.sh
```

4) Build image using Dockerfile
```
cd ./docker
docker build -t spil/slc-puppet:6.5 .
```

# Usage
Use ./docker/puppet_test.py
* Create virtualenv and install dependencies
```
virtualenv .env
source .env/bin/activate
pip install -r requirements.txt
```

* Check details of usage
```
./docker/puppet_test.py -h
```
# Examples
start testing of modules :nginx,mysql,erlang
enable 'quick' mode:  if base image exist it will be reused
run tests in parallel: use 3 workers
```
./docker/puppet_test.py --quick -m nginx,mysql,erlang -p 3 --puppet-directory /vagrant/puppet_test
```
test all modules with test class
```
./docker/puppet_test.py --quick -a -p 10 --puppet-directory /vagrant/puppet_test
```
