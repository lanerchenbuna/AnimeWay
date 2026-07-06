# Retrieval Cache

This directory is reserved for optional local retrieval caches.

To enable the BM25 cache during development:

```bash
export ANIMEWAY_RETRIEVAL_CACHE_DIR="knowledge_base/vector_cache"
```

The cache is generated from `knowledge_base/index.json` and can be deleted safely.
