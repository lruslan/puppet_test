puppet_test
===========

Functional testing of Puppet modules

This repository contain puppet demo environment with automation scripts

All scripts located inside ./docker directory

Main automation script is ./docker/puppet_test.py

Current project is used and tested on SLC6 and should work on RHEL6 as well 


# Installation and configuration

Make sure SELinux is disabled

To disable SELinux:

1) Change configuration and reboot server

/etc/selinux/config:
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
For module testing use script ./docker/puppet_test.py

Create virtualenv and install dependencies:
```
virtualenv .env
source .env/bin/activate
pip install -r docker/requirements.txt
```

Check details of script usage:
```
./docker/puppet_test.py -h
```
# Examples
- start testing of modules: nginx,mysql,erlang
- enable 'quick' mode:  if base image exist it will be reused
- run tests in parallel: use 3 workers
```
./docker/puppet_test.py --quick -m nginx,mysql,erlang -p 3 --puppet-directory /vagrant/puppet_test
```

- run all modules with tests
```
./docker/puppet_test.py --quick -a -p 10 --puppet-directory /vagrant/puppet_test
```

# Reports
Script will generate 'report' folder (by default inside working directory)
With two type of reports:
* 'html' subdirectory contain overview of testing results in html format, 
* set of directories with details about tests in yaml format

# Running as a Jenkins job
Make sure jenkins user are belongs to group 'docker'
```
usermod -a -G docker jenkins
```
In order to track changes 
