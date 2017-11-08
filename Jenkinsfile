def onmyduffynode(script){
    ansiColor('xterm'){
        timestamps{
            sh 'ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -l root ${DUFFY_NODE}.ci.centos.org -t "' + script + '"'
        }
    }
}

def syncfromduffynode(rsyncpath){
    sh 'rsync -e "ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -l root " -Ha --include=' +  rsyncpath +  " ${DUFFY_NODE}.ci.centos.org:~/ ./"
}

node('factory2'){

    stage('Allocate Node'){
        env.CICO_API_KEY = readFile("${env.HOME}/duffy.key").trim()
        duffy_rtn=sh(
            script: 'cico --debug node get -f value -c hostname -c comment',
            returnStdout: true
            ).trim().tokenize(' ')
        env.DUFFY_NODE=duffy_rtn[0]
        env.SSID=duffy_rtn[1]
    }

    try{
        stage('Pre Setup Node'){
            onmyduffynode 'yum -y install epel-release'
            // We are using the system version of python-moksha-hub because it uses a version of Twisted that is 
            // compatible with the system version of pyOpenSSL. This can all be shifted into a virtualenv once
            // koji is on PyPi.
            onmyduffynode 'yum -y install @development python-pip python-devel krb5-devel openssl-devel koji python-moksha-hub swig createrepo_c'
        }

        stage('Clone Test Suite') {
            onmyduffynode "git clone -b \"${env.BRANCH_NAME}\" https://pagure.io/fm-orchestrator"
        }

        stage('Run Test Suite') {
            onmyduffynode 'cd fm-orchestrator && pip install -r requirements.txt && pip install -r test-requirements.txt && python setup.py develop && flake8 --ignore E731 --exclude .tox,.git,module_build_service/migrations && pytest -v tests/'
        }

    }catch (e){
        currentBuild.result = "FAILED"
        throw e 
    } finally {
        stage('Deallocate Node'){
            sh 'cico node done ${SSID}'
        }
    }
}
