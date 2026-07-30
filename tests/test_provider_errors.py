"""Provider error taxonomy + retry semantics (directive section 6 / FINAL
DELIVERY §5, §11).

Covers the full classification contract: quota, authentication, timeout,
permanent 4xx, retryable 5xx, malformed/corrupt responses, and unavailable
provider — and which of those are retryable."""
from __future__ import annotations

import pytest

from rusted_recall.providers.base import classify_http_error
from rusted_recall.providers.genblaze_official import _classify
from rusted_recall.repair import (
    ERR_AUTH,
    ERR_CORRUPT,
    ERR_INVALID,
    ERR_QUOTA,
    ERR_RATE_LIMIT,
    ERR_SAFETY,
    ERR_TIMEOUT,
    ERR_UNAVAILABLE,
    is_retryable,
)


@pytest.mark.parametrize(
    "code,category",
    [
        (401, ERR_AUTH),
        (403, ERR_AUTH),
        (402, ERR_QUOTA),
        (429, ERR_RATE_LIMIT),
        (400, ERR_INVALID),
        (404, ERR_INVALID),
        (422, ERR_INVALID),
        (451, ERR_SAFETY),
        (408, ERR_TIMEOUT),
        (504, ERR_TIMEOUT),
        (500, ERR_UNAVAILABLE),
        (503, ERR_UNAVAILABLE),
    ],
)
def test_http_status_taxonomy(code, category):
    assert classify_http_error(code) == category


def test_retryability_contract():
    # Transient categories retry; permanent categories never do.
    assert is_retryable(ERR_RATE_LIMIT)
    assert is_retryable(ERR_TIMEOUT)
    assert is_retryable(ERR_UNAVAILABLE)
    assert is_retryable(ERR_CORRUPT)
    assert not is_retryable(ERR_AUTH)
    assert not is_retryable(ERR_QUOTA)
    assert not is_retryable(ERR_INVALID)
    assert not is_retryable(ERR_SAFETY)


def test_quota_is_permanent_not_retried():
    # 402 insufficient credits must NOT be retried (avoids hammering a
    # credit-blocked account); it is surfaced honestly for owner action.
    assert classify_http_error(402) == ERR_QUOTA
    assert not is_retryable(ERR_QUOTA)


def test_official_classifier_trusts_concrete_codes_over_message():
    # A genuine retryable server_error must stay retryable even if its message
    # contains words like "invalid"/"not found" (PR #7 regression).
    cat = _classify("server_error", "Upstream 503: invalid gateway, not found")
    assert cat == ERR_UNAVAILABLE
    assert is_retryable(cat)
    assert _classify("invalid_input", "bad prompt") == ERR_INVALID
    assert not is_retryable(_classify("invalid_input", "bad prompt"))


def test_official_classifier_recovers_from_flattened_unknown():
    # When the upstream flattens the code to 'unknown', recover from the message.
    assert _classify("unknown", "submit failed (402): Insufficient credits") == ERR_QUOTA
    assert _classify("unknown", "401 Unauthorized") == ERR_AUTH
    assert _classify("unknown", "429 rate limit exceeded") == ERR_RATE_LIMIT
    assert _classify("unknown", "connection timed out") == ERR_TIMEOUT
