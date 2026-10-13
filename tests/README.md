# Automated Python Tests

This directory contains the supported automated regression suite.

Run all tests from the repository root:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

Rules:

- Automated tests belong here.
- Manual smoke/diagnostic scripts do not.
- Tests must be safe to import during discovery.
- Prefer temporary directories and mocked external processes/services.
- Keep production-path integration tests for critical pipelines such as summary/memory composition and artifact lifecycle.
