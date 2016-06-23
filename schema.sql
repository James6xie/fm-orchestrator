CREATE TABLE IF NOT EXISTS modules (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL, -- e.g. foo, module name
    version   TEXT NOT NULL, -- e.g. 1.23, module version
    release   TEXT NOT NULL, -- e.g. 4, module release
    state     TEXT NOT NULL, -- init, wait, build, done, failed, ready
    modulemd  TEXT NOT NULL  -- the entire modulemd file
);

CREATE TABLE IF NOT EXISTS builds (
    id        INTEGER PRIMARY KEY,
    module_id INTEGER NOT NULL,
    package   TEXT NOT NULL,    -- e.g. bar, SRPM name
    format    TEXT NOT NULL,    -- rpm
    task      INTEGER NOT NULL, -- koji task id
    state     TEXT NOT NULL,    -- koji build states - open, closed, failed
    FOREIGN KEY(module_id) REFERENCES modules(id)
);
