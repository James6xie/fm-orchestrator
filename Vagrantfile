# -*- mode: ruby -*-
# vi: set ft=ruby ts=2 sw=2 ai et:

$script = <<SCRIPT
    grep -q '^127\.0\.0\.1 fedmsg-relay$' /etc/hosts || echo "127.0.0.1 fedmsg-relay" >> /etc/hosts
    echo "export MODULE_BUILD_SERVICE_DEVELOPER_ENV=1" > /etc/profile.d/module_build_service_developer_env.sh
    source /etc/profile.d/module_build_service_developer_env.sh
    dnf install -y \
        fedmsg-hub \
        fedmsg-relay \
        fedpkg \
        gcc \
        gcc-c++ \
        git \
        koji \
        krb5-workstation \
        libffi-devel \
        libmodulemd \
        mock-scm \
        openssl-devel \
        python \
        python-devel \
        python-docutils \
        python-flask \
        python-gobject-base \
        python-m2ext \
        python-mock \
        python-qpid \
        python-solv \
        python-sqlalchemy \
        python-virtualenv \
        python-futures \
        python2-pungi \
        python3 \
        python3-devel \
        python3-docutils \
        python3-pungi \
        redhat-rpm-config \
        redhat-rpm-config \
        rpm-build \
        swig \
        sqlite \
        glib2-devel \
        cairo-devel \
        cairo-gobject-devel \
        gobject-introspection-devel \
        bash-completion \
        wget \
        which

    if [ ! -e /etc/module-build-service ]; then
        ln -s /opt/module_build_service/conf /etc/module-build-service
    fi
SCRIPT

$make_devenv = <<DEVENV
  env_dir=~/devenv
  pip=${env_dir}/bin/pip
  py=${env_dir}/bin/python
  code_dir=/opt/module_build_service

  test -e $env_dir && rm -rf $env_dir

  # solv is not availabe from pypi.org. libsolve has to be installed by dnf.
  (cd; virtualenv --system-site-packages devenv)

  $pip install --upgrade pip
  $pip install -r $code_dir/test-requirements.txt
  $pip install ipython

  cd $code_dir
  $py setup.py develop
  $py setup.py egg_info

  if ! grep ". $env_dir/bin/activate" ~/.bashrc >/dev/null; then
      echo ". $env_dir/bin/activate" >> ~/.bashrc
  fi
  if ! grep "^cd $code_dir" ~/.bashrc >/dev/null; then
      # Go to working directory after login
      echo "cd $code_dir" >> ~/.bashrc
  fi
DEVENV

$script_services = <<SCRIPT_SERVICES
    bin_dir=~/devenv/bin
    cd /opt/module_build_service
    $bin_dir/mbs-upgradedb > /tmp/mbs-base.out 2>&1
    $bin_dir/fedmsg-relay < /dev/null >& /tmp/fedmsg-relay.out &
    $bin_dir/fedmsg-hub < /dev/null >& /tmp/fedmsg-hub.out &
    $bin_dir/mbs-frontend < /dev/null >& /tmp/mbs-frontend.out &
SCRIPT_SERVICES

Vagrant.configure("2") do |config|
  config.vm.box = "fedora/27-cloud-base"
  config.vm.synced_folder "./", "/opt/module_build_service"
  # Disable the default share
  config.vm.synced_folder ".", "/vagrant", disabled: true
  config.vm.network "forwarded_port", guest_ip: "0.0.0.0", guest: 5000, host: 5000
  config.vm.network "forwarded_port", guest_ip: "0.0.0.0", guest: 13747, host: 13747
  config.vm.provision "shell", inline: $script
  config.vm.provision "shell", inline: "usermod -a -G mock Vagrant"
  config.vm.provision "shell", inline: $make_devenv, privileged: false
  config.vm.provision "shell", inline: $script_services, privileged: false, run: "always"
  config.vm.provider "libvirt" do |v, override|
    override.vm.synced_folder "./", "/opt/module_build_service", type: "sshfs", sshfs_opts_append: "-o nonempty"
    v.memory = 1024
    #v.cpus = 2
  end
  config.vm.provider "virtualbox" do |v|
    v.memory = 1024
    #v.cpus = 2
  end
end
