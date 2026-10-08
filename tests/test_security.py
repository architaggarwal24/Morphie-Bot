import pytest

from morphie import security
from morphie.security import RateLimiter, is_trusted_origin


# ---- rate limiter ----

class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_rate_limiter_allows_up_to_the_limit_then_blocks_with_a_retry_hint():
    clock = _Clock()
    limiter = RateLimiter(limit=3, window_seconds=60, clock=clock)
    assert [limiter.check("u")[0] for _ in range(3)] == [True, True, True]
    allowed, retry_after = limiter.check("u")
    assert allowed is False and 1 <= retry_after <= 60


def test_rate_limiter_window_slides_and_keys_are_independent():
    clock = _Clock()
    limiter = RateLimiter(limit=2, window_seconds=60, clock=clock)
    limiter.check("a"); limiter.check("a")
    assert limiter.check("a")[0] is False
    assert limiter.check("b")[0] is True                 # another user is unaffected
    clock.now += 61
    assert limiter.check("a")[0] is True                 # the window has moved on


def test_rate_limiter_memory_is_bounded_even_with_many_distinct_keys():
    limiter = RateLimiter(limit=5, window_seconds=60, max_keys=100, clock=_Clock())
    for i in range(1000):
        limiter.check(f"user-{i}")
    assert limiter.tracked_keys() <= 100


def test_a_zero_or_negative_limit_disables_limiting():
    limiter = RateLimiter(limit=0, window_seconds=60, clock=_Clock())
    assert all(limiter.check("u")[0] for _ in range(1000))


# ---- CSRF: origin checking ----

HOST = "morphie.example:5000"


@pytest.mark.parametrize("headers", [
    {},                                                        # non-browser client / same-origin without Origin
    {"Origin": "http://morphie.example:5000"},
    {"Origin": "https://morphie.example:5000"},
    {"Sec-Fetch-Site": "same-origin"},
    {"Sec-Fetch-Site": "none"},
])
def test_same_origin_and_non_browser_requests_are_allowed(headers):
    assert is_trusted_origin(headers, HOST) is True


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},
    {"Origin": "http://morphie.example:6000"},                 # different port = different origin
    {"Origin": "null"},                                        # sandboxed / opaque origins
    {"Origin": "http://morphie.example.evil.example"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},                           # a sibling subdomain is still not us
    {"Origin": "not a url"},
])
def test_cross_site_requests_are_rejected(headers):
    assert is_trusted_origin(headers, HOST) is False


def test_explicitly_trusted_origins_are_allowed():
    assert is_trusted_origin({"Origin": "https://app.example.com"}, HOST, trusted=["https://app.example.com"]) is True
    assert is_trusted_origin({"Origin": "https://evil.example"}, HOST, trusted=["https://app.example.com"]) is False
