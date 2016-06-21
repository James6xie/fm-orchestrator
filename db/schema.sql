CREATE TABLE IF NOT EXISTS modules (
	id        INTEGER PRIMARY KEY,
	name      TEXT NOT NULL, -- foo-1.23-4, module NVR
	state     TEXT NOT NULL  -- init, building, done, failed, locked
);

CREATE TABLE IF NOT EXISTS builds (
	id        INTEGER PRIMARY KEY,
	module_id INTEGER NOT NULL,
	package   TEXT NOT NULL,    -- bar-42-1, SRPM NVR
	type      TEXT NOT NULL,    -- rpm
	task      INTEGER NOT NULL, -- koji task id
	state     TEXT NOT NULL,    -- koji build states - open, closed, failed
	FOREIGN KEY(module_id) REFERENCES modules(id)
);
