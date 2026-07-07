# Security Policy

## Reporting vulnerabilities

- Email: `security@geteqo.ai`
- Do **not** open public GitHub issues for security vulnerabilities
- Include the following in your report:
  - Description of the issue
  - Reproduction steps
  - Affected versions
  - Impact assessment

## Response commitment

- Acknowledgment within 48 hours of report
- Status update within 7 business days
- Disclosure timing will be coordinated with the reporter

## Safe harbor

We will not pursue legal action against researchers who discover and report vulnerabilities in good faith, in accordance with this policy, without accessing or exfiltrating data beyond what's necessary to demonstrate the issue. There is no bug bounty program and no compensation for reports.

## Supported versions

Security updates are provided for the latest release only.

## Encrypted reporting

We do not currently offer a PGP key. If you need to share sensitive details securely, email the address above to arrange an alternative secure channel before sending them.

## Known limitations

Some properties of v1.0.0 are intentional design limitations, not bugs: tamper-evidence is anchor-relative, records are unsigned (`entry_signature` is `null`), and tail-truncation requires an external reference to detect. These are documented in the Security Model section of [`docs/spec.md`](docs/spec.md) — check there before reporting on one of them. Genuine implementation flaws are still very much wanted.

## Scope

In scope:

- Vulnerabilities in the `pbom` Python package (hashing, commitment scheme, chain validation, file I/O)
- Vulnerabilities in the PBOM record format that could lead to integrity bypass

Out of scope:

- Vulnerabilities in third-party dependencies (please report those upstream)
