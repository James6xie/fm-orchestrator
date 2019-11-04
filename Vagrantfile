# -*- mode: ruby -*-
# vi: set ft=ruby ts=2 sw=2 ai et:

$script = <<SCRIPT
    set -e
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
        krb5-devel \
        krb5-workstation \
        libffi-devel \
        mock-scm \
        openssl-devel \
        python \
        python-devel \
        python2-dnf \
        python-docutils \
        python-flask \
        python2-libmodulemd \
        python-m2ext \
        python-mock \
        python-qpid \
        python-solv \
        python-sqlalchemy \
        python-futures \
        python2-pungi \
        python3 \
        python3-devel \
        python3-docutils \
        python3-pungi \
        python3-virtualenv \
        redhat-rpm-config \
        redhat-rpm-config \
        rpm-build \
        swig \
        sqlite \
        bash-completion \
        wget \
        which

    mbs_config_dir=/etc/module-build-service
    [ -e "$mbs_config_dir" ] || mkdir "$mbs_config_dir"
    cp -r /opt/module_build_service/conf/* "$mbs_config_dir"
SCRIPT

$make_devenv = <<DEVENV
  set -e
  env_dir=~/devenv
  pip=${env_dir}/bin/pip
  py=${env_dir}/bin/python
  code_dir=/opt/module_build_service

  test -e $env_dir && rm -rf $env_dir

  # solv is not availabe from pypi.org. libsolv has to be installed by dnf.
  (cd; virtualenv -p python2 --system-site-packages devenv)

  $pip install --upgrade pip kobo
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

$config_pgsql = <<PGSQL
dnf install -y postgresql postgresql-server python2-psycopg2

pg_hba_conf=/var/lib/pgsql/data/pg_hba.conf

if [[ ! -e "$pg_hba_conf" ]]; then
  postgresql-setup --initdb
fi

systemctl start postgresql
systemctl enable postgresql

cp "$pg_hba_conf" "${pg_hba_conf}.orig"

# Allow to connect to PostgreSQL without password
if ! grep "host all all 127.0.0.1/32 trust" "$pg_hba_conf" >/dev/null; then
  echo "host all all 127.0.0.1/32 trust" > "$pg_hba_conf"
fi

# Avoid SQL query statement being truncated in pg_stat_activity, which is
# convenient for debugging.
pg_conf=/var/lib/pgsql/data/postgresql.conf
if ! grep "track_activity_query_size = 4096" "$pg_conf" >/dev/null; then
  echo "track_activity_query_size = 4096" >> "$pg_conf"
fi

# Restart to apply configuration changes
systemctl restart postgresql

psql -U postgres -h 127.0.0.1 -c "DROP DATABASE IF EXISTS mbstest"
psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE mbstest"

bashrc=/home/vagrant/.bashrc

echo "******** Run Tests with PostgreSQL ********"
echo "Set this environment variable to test with PostgreSQL"
echo "export DATABASE_URI=postgresql+psycopg2://postgres:@127.0.0.1/mbstest"
echo
PGSQL

$script_services = <<SCRIPT_SERVICES
    bin_dir=~/devenv/bin
    cd /opt/module_build_service
    $bin_dir/mbs-upgradedb > /tmp/mbs-base.out 2>&1
    $bin_dir/fedmsg-relay < /dev/null >& /tmp/fedmsg-relay.out &
    $bin_dir/fedmsg-hub < /dev/null >& /tmp/fedmsg-hub.out &
    $bin_dir/mbs-frontend < /dev/null >& /tmp/mbs-frontend.out &
SCRIPT_SERVICES

Vagrant.configure("2") do |config|
  config.vm.box = "fedora/31-cloud-base"
  config.vm.synced_folder "./", "/opt/module_build_service"
  # Disable the default share
  config.vm.synced_folder ".", "/vagrant", disabled: true
  config.vm.network "forwarded_port", guest_ip: "0.0.0.0", guest: 5000, host: 5000
  config.vm.network "forwarded_port", guest_ip: "0.0.0.0", guest: 13747, host: 13747
  config.vm.provision "shell", inline: $script
  config.vm.provision "shell", inline: "usermod -a -G mock vagrant"
  config.vm.provision "shell", inline: $config_pgsql
  config.vm.provision "shell", inline: $make_devenv, privileged: false
  config.vm.provision "shell", inline: $script_services, privileged: false, run: "always"
  config.vm.provider "libvirt" do |v, override|
    override.vm.synced_folder "./", "/opt/module_build_service", type: "sshfs"
    v.memory = 1024
  end
  config.vm.provider "virtualbox" do |v|
    v.memory = 1024
  end
end
