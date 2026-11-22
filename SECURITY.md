# Security

## Reporting a vulnerability

Please report it privately, not in a public issue:
go to the repository's **Security** tab, then **Report a vulnerability**
(https://github.com/falcon883/obd-dashboard/security/advisories/new).

Include what you found, how to reproduce it and which version you used. You will get a reply within a few days.
This is a hobby project run by one person, so there is no bug bounty and no fixed fix time, but real problems are
taken seriously and you will be credited if you like.

## Things worth knowing

- The server listens on `127.0.0.1` by default. With `--host 0.0.0.0` it has **no login**: anyone on the network can
  see the data and start or stop the logger. That is a known limit, so only use it on a network you trust.
- The app never writes to the car and never sends the command that clears codes.
- The only outgoing request is the optional VIN lookup on NHTSA's public service (`--no-vin-lookup` turns it off).
- Log downloads only serve files inside the logs folder.

Only the latest release gets fixes.
