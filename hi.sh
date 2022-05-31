#!/usr/bin/env sh
kill `cat /tmp/wd_pid`
pipenv run -- bp strips.yml &
echo "$!" > /tmp/wd_pid
