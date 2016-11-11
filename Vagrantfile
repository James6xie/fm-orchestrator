# -*- mode: ruby -*-
# vi: set ft=ruby :

$script = <<SCRIPT
    dnf install -y \
        python \
        python-virtualenv \
        python-devel \
        libffi-devel \
        redhat-rpm-config \
        openssl-devel \
        gcc \
        gcc-c++ \
        koji \
        git \
        swig \
        fedmsg-relay \
        rpm-build \
        python-mock \
        krb5-workstation
    pip install -r /opt/module_build_service/requirements.txt
    pip install -r /opt/module_build_service/test-requirements.txt
    cd /opt/module_build_service
    mkdir -p /etc/module_build_service
    ln -s /opt/module_build_service/koji.conf /etc/module_build_service/koji.conf
    ln -s /opt/module_build_service/copr.conf /etc/module_build_service/copr.conf
    ln -s /opt/module_build_service/krb5-stg.fp.o /etc/krb5.conf.d/stg_fedoraproject_org
    python manage.py upgradedb
    python manage.py generatelocalhostcert
    systemctl start fedmsg-relay
    echo "export KRB5CCNAME=FILE:/var/tmp/krbcc" >> ~/.bashrc
SCRIPT

Vagrant.configure("2") do |config|
  config.vm.box = "boxcutter/fedora24"
  config.vm.synced_folder "./", "/opt/module_build_service"
  config.vm.provision "file", source: "/var/tmp/krbcc", destination: "/var/tmp/krbcc", run: "always"
  config.vm.network "forwarded_port", guest: 5000, host: 5000
  config.vm.provision "shell", inline: $script
  config.vm.provision :shell, inline: "cd /opt/module_build_service && python manage.py runssl --debug &", run: "always"
  config.vm.provision :shell, inline: "cd /opt/module_build_service && python module_build_service_daemon.py &", run: "always"
end
