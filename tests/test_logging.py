from fsbench.logging import SecretScrubber


def test_secret_scrubber_redacts_short_secret() -> None:
    # ARRANGE
    scrubber = SecretScrubber()
    scrubber.register_secret(env_name="TINY_TOKEN", value="abc")

    # ACT
    scrubbed = scrubber.scrub_text("token=abc")

    # ASSERT
    assert scrubbed == "token=<TINY_TOKEN>"
