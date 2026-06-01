from app.services.service_identity import LOTUS_PERFORMANCE_CONSUMER_SYSTEM


def test_lotus_performance_consumer_system_identity_is_canonical():
    assert LOTUS_PERFORMANCE_CONSUMER_SYSTEM == "lotus-performance"
