# Loopback TLS fixture

`localhost-cert.pem` and `localhost-key.pem` are public, test-only self-signed
material, generated solely for the isolated HTTP tests. They identify only
`127.0.0.1` and `localhost`, contain no user credentials, and must never be used
outside tests. The certificate expires in 2036; its OpenSSL subject hash is
`8461719e` (used to test `SSL_CERT_DIR` without a runtime OpenSSL CLI dependency).
