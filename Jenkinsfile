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
            // Install EPEL and the SCLs repo
            onmyduffynode 'yum -y install git docker && systemctl start docker'
        }

        stage('Clone Test Suite') {
            onmyduffynode "git clone -b \"${env.BRANCH_NAME}\" --single-branch --depth 1 https://pagure.io/fm-orchestrator"
        }

        stage('Build Docker Image') {
            onmyduffynode 'cd fm-orchestrator && docker build -t mbs/test -f docker/Dockerfile-tests .'
        }

        stage('Run Test Suite') {
            timeout(20) {
                onmyduffynode 'docker run -v ~/fm-orchestrator:/src:Z mbs/test'
            }
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
