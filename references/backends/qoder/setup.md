# Qoder CLI Setup and Readiness

Use this guide for first use, login or binary changes, upgrades, or readiness
repair. For ordinary review behavior, return to [runtime.md](runtime.md).

The host must provide an executable named `qodercli` and a valid Qoder login.
The `backends` listing proves only that the executable and bundled adapter were
discovered; it does not attest login state or model access.

Before the first review:

1. Run `python3 scripts/independent-review.py backends` and confirm that
   `qoder` is available.
2. If multiple installations exist, select the intended absolute binary with
   dispatcher `--bin qodercli=/absolute/path/to/qodercli` or the non-secret
   `INDEPENDENT_REVIEW_QODERCLI_BIN` setting.
3. Complete Qoder's normal host login for that installation. If a classified
   runtime failure reports `logged_out`, run `qodercli login` manually; the
   review workflow must not open the browser or log in for the user.
4. Run a small review only when one real model invocation is authorized.

Do not inspect or emit environment or credential values while diagnosing the
login. After changing the executable, login, or Qoder version, repeat discovery
and one authorized smoke before relying on the backend for a review gate.
