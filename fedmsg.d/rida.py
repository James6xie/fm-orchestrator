import socket
hostname = socket.gethostname().split('.')[0]

config = {
    # Just enough fedmsg config to start publishing...
    "endpoints": {
        "rida.%s" % hostname: [
            "tcp://127.0.0.1:300%i" % i for i in range(10)
        ],
    },

    # Start of code signing configuration
    # 'sign_messages': True,
    # 'validate_signatures': True,
    # 'crypto_backend': 'x509',
    # 'crypto_validate_backends': ['x509'],
    # 'ssldir': '/opt/fm-orchestrator/pki',
    # 'crl_location': 'http://localhost/crl/ca.crl',
    # 'crl_cache': '/etc/pki/fedmsg/crl.pem',
    # 'crl_cache_expiry': 10,
    # 'ca_cert_location': 'http://localhost/crl/ca.crt',
    # 'ca_cert_cache': '/etc/pki/fedmsg/ca.crt',
    # 'ca_cert_cache_expiry': 0,  # Never expires
    # 'certnames': {
    #     'rida.localhost': 'localhost'
    # }
    # End of code signing configuration
}
