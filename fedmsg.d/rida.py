import socket
hostname = socket.gethostname().split('.')[0]

config = {
    # Just enough fedmsg config to start publishing...
    "endpoints": {
        "rida.%s" % hostname: [
            "tcp://127.0.0.1:300%i" % i for i in range(10)
        ],
    },
}
