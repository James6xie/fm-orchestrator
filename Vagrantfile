# -*- mode: ruby -*-
# vi: set ft=ruby :

$script = <<SCRIPT
    dnf install -y python python-virtualenv python-devel libffi-devel redhat-rpm-config openssl-devel gcc gcc-c++ koji git swig fedmsg-relay rpm-build
    pip install -r /opt/module_build_service/src/requirements.txt
    pip install -r /opt/module_build_service/src/test-requirements.txt
    cd /opt/module_build_service/src
    mkdir -p /etc/module_build_service
    cp -av koji.conf /etc/module_build_service/
    cp -av copr.conf /etc/module_build_service/
    python manage.py upgradedb
    python manage.py generatelocalhostcert
    cp /home/vagrant/.fedora-server-ca.cert /root/.fedora-server-ca.cert
    cp /home/vagrant/.fedora-upload-ca.cert /root/.fedora-upload-ca.cert
    cp /home/vagrant/.fedora.cert /root/.fedora.cert
    systemctl start fedmsg-relay
SCRIPT

Vagrant.configure("2") do |config|
  config.vm.box = "boxcutter/fedora24"
  config.vm.synced_folder "./", "/opt/module_build_service/src"
  config.vm.provision "file", source: "~/.fedora-server-ca.cert", destination: "~/.fedora-server-ca.cert"
  config.vm.provision "file", source: "~/.fedora-upload-ca.cert", destination: "~/.fedora-upload-ca.cert"
  config.vm.provision "file", source: "~/.fedora.cert", destination: "~/.fedora.cert"
  config.vm.network "forwarded_port", guest: 5000, host: 5000
  config.vm.provision "shell", inline: $script
  config.vm.provision :shell, inline: "cd /opt/module_build_service/src && python manage.py runssl --debug &", run: "always"
  config.vm.provision :shell, inline: "cd /opt/module_build_service/src && python module_build_service_daemon.py &", run: "always"
end
