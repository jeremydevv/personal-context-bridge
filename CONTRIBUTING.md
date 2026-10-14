# Contributing

Use development branches and run the README's validation commands before opening
a pull request. Keep runtime state outside your checkout. Do not include personal
records in bug reports or test fixtures; reproduce failures with made-up records.
Record provenance and licenses for externally supplied fixtures or adapted code.

Changes to authentication, complete-snapshot deletion, encryption, attachment
handling, or write operations need regression tests. Check package contents as
well as tracked files. Do not weaken permission checks to make a test pass.
macOS/iPhone permissions and live account authentication require device validation;
CI verifies synthetic protocol and archive behavior only.
