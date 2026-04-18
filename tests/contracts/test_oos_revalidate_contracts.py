from tools import oos_revalidate


def test_extract_function_signature_handles_type_annotations():
    source = """
def fetch_funding_rate(symbol: str, limit: int = 100,
                       end_time_ms: int | None = None) -> pd.DataFrame | None:
    return None
"""
    signature = oos_revalidate._extract_function_signature(source, "fetch_funding_rate")
    assert signature is not None
    assert "symbol: str" in signature
    assert "end_time_ms: int | None = None" in signature


def test_scan_method_risks_does_not_flag_bounded_sentiment():
    spec = oos_revalidate.ENGINES["bridgewater"]
    notes = oos_revalidate._scan_method_risks(spec)
    assert not any("LIVE_SENTIMENT_UNBOUNDED" in note for note in notes)
