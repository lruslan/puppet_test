#docker build -t spil/slc-auto .
FROM spil/slc:6.5
MAINTAINER Ruslan Lutsenko

RUN yum install -y  perl-libwww-perl
RUN yum reinstall -y  -v cracklib-dicts
RUN yum install -y openssh-server
RUN yum install -y rsync
RUN yum install -y sudo
#puppet
ADD Puppet-EL6.repo /etc/yum.repos.d/Puppet-EL6.repo
ADD Puppet-deps-EL6.repo /etc/yum.repos.d/Puppet-deps-EL6.repo
RUN yum install -y rubygem-deep-merge
RUN yum install -y puppet
#ssh
RUN mkdir /root/.ssh
ADD docker_rsa.pub /root/.ssh/authorized_keys
ADD sshd_config /etc/ssh/sshd_config

CMD /etc/init.d/sshd start && /bin/bash
