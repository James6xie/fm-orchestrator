config = {
    # Just for dev.
    "validate_signatures": False,

    # Talk to the relay, so things also make it to composer.stg in our dev env
    "active": True,

    # Since we're in active mode, we don't need to declare any of our own
    # passive endpoints.  This placeholder value needs to be here for the tests
    # to pass in Jenkins, though.  \o/
    "endpoints": {
        "fedora-infrastructure": [
            # Just listen to staging for now, not to production (spam!)
            #"tcp://hub.fedoraproject.org:9940",
            "tcp://stg.fedoraproject.org:9940",
        ],
        "relay_outbound": [
            "tcp://fedmsg-relay:2001"
        ],
    },
    "relay_inbound": [
        "tcp://fedmsg-relay:2003"
    ],

    # Start of code signing configuration
    # 'sign_messages': True,
    # 'validate_signatures': True,
    # 'crypto_backend': 'x509',
    # 'crypto_validate_backends': ['x509'],
    # 'ssldir': '/opt/module_build_service/pki',
    # 'crl_location': 'http://localhost/crl/ca.crl',
    # 'crl_cache': '/etc/pki/fedmsg/crl.pem',
    # 'crl_cache_expiry': 10,
    # 'ca_cert_location': 'http://localhost/crl/ca.crt',
    # 'ca_cert_cache': '/etc/pki/fedmsg/ca.crt',
    # 'ca_cert_cache_expiry': 0,  # Never expires
    # 'certnames': {
    #     'module_build_service.localhost': 'localhost'
    # }
    # End of code signing configuration
}
