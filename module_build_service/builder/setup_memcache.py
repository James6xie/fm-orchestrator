/*set up memcache server for koji perm_ids*/

my $memclient = Cache::Memcached->new({ servers => [ '10.0.0.10:11211', '10.0.0.11:11211' ]});
memcli = new Memcache
memcli:add_server('10.0.0.10:11211')

sql = "SELECT * FROM user WHERE user_id = ?"
key = 'SQL:' . user_id . ':' . md5sum(sql)

if (defined result = memcli:get(key)) {
	return result
} else {
	handler = run_sql(sql, user_id)

	# Often what you get back when executing SQL is a special handler
	# object. You can't directly cache this. Stick to strings, arrays,
	# and hashes/dictionaries/tables
	rows_array = handler:turn_into_an_array

	# Cache it for five minutes
	memcli:set(key, rows_array, 5 * 60)

	return rows_array
}
