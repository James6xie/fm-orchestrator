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
        fedpkg \
        python-mock \
        krb5-workstation \
        systemd-devel \
        gcc \
        redhat-rpm-config \
        python-devel \
        python-flask
    cd /tmp/module_build_service
    python setup.py install
    mbs-upgradedb
    mbs-gencert
    systemctl enable fedmsg-relay
    systemctl start fedmsg-relay
    echo "export KRB5CCNAME=FILE:/var/tmp/krbcc" >> ~/.bashrc
SCRIPT

Vagrant.configure("2") do |config|
  # $ wget https://download.fedoraproject.org/pub/fedora/linux/releases/24/CloudImages/x86_64/images/Fedora-Cloud-Base-Vagrant-24-1.2.x86_64.vagrant-libvirt.box && \
  #   vagrant box add Fedora-Cloud-Base-Vagrant-24-1.2.x86_64.vagrant-libvirt.box --name fedora-24
  config.vm.box = "fedora-24"
  config.vm.synced_folder "./", "/tmp/module_build_service"
  config.vm.provision "file", source: "/var/tmp/krbcc", destination: "/var/tmp/krbcc", run: "always"
  config.vm.network "forwarded_port", guest: 5000, host: 5000
  config.vm.provision "shell", inline: $script
  config.vm.provision :shell, inline: "mbs-frontend &", run: "always"
  config.vm.provision :shell, inline: "mbs-daemon &", run: "always"
end
