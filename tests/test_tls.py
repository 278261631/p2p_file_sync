import ssl

from pfs.net.tls import build_client_ssl_context


def test_default_context_uses_a_real_bundle(monkeypatch):
    monkeypatch.delenv("PFS_TLS_CA", raising=False)
    ctx = build_client_ssl_context()
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    # certifi ships many roots; a bare system store would not be asserted here.
    assert len(ctx.get_ca_certs()) > 1


def test_pfs_tls_ca_override_limits_bundle(tmp_path, monkeypatch):
    import certifi

    pem = open(certifi.where(), encoding="utf-8").read()
    first = pem.split("-----END CERTIFICATE-----")[0] + "-----END CERTIFICATE-----\n"
    ca = tmp_path / "ca.pem"
    ca.write_text(first, encoding="utf-8")

    monkeypatch.setenv("PFS_TLS_CA", str(ca))
    ctx = build_client_ssl_context()
    assert len(ctx.get_ca_certs()) == 1
