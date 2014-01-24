# Install docker and dependencies
yum install -y docker-io
yum install -y perl-libwww-perl
# Start docker
/etc/init.d/docker start
# Install rinse http://www.steve.org.uk/Software/rinse/
tar -xvf rinse-2.0.1.tar.gz
cd rinse-2.0.1
make install
cd ..
rm -fr rinse-2.0.1
# Build image
./mkimage-rinse.sh spil/slc slc-6
