#!/usr/bin/python3

import rida.config
import rida.database

config = rida.config.from_file("rida.conf")

rida.database.Database.create_tables(config.db, True)
