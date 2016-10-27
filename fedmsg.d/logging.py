# Setup fedmsg logging.
# See the following for constraints on this format https://bit.ly/Xn1WDn
bare_format = "[%(asctime)s][%(name)10s %(levelname)7s] %(message)s"

config = dict(
    logging=dict(
        loggers=dict(
            # Quiet this guy down...
            requests={
                "level": "WARNING",
                "propagate": True,
                "handlers": ["console"],
            },
        ),
    ),
)
