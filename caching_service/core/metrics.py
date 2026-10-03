from prometheus_client import Counter

# Every call is a paid call to the external service, so this is the number the cache exists to keep low.
# Exposed as ``transformer_calls_total``.
TRANSFORMER_CALLS = Counter("transformer_calls", "Calls made to the transformer (cache misses).")
