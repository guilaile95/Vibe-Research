# Linux user-space package

This is the existing browser application with a Linux installer and foreground
launcher, **not a native desktop app or cloud deployment**. It uses the existing
loopback addresses: frontend 5899, backend 8900, Node agent runtime 8911. No sudo,
system services, new browser, tunnels or security-policy changes are involved.

The current managed cloud browser's access restriction remains unresolved. This
package does not make that browser able to reach the app. Installation and live
browser acceptance have not been performed in that environment; packaging and
mocked lifecycle tests do not establish usable cloud deployment.

## Prerequisites and build

Linux, Python **3.11** with venv/pip, Node.js **22.6+**, npm, and sufficient disk
space. Building from a checkout also requires git. Optional `xdg-open` uses your existing default browser. Python/Node and
third-party dependencies are not bundled: this is not a fully offline package.
Installation requires access to npm/PyPI and any platform prerequisites needed by
the locked dependencies; Linux architectures other than the validation host are
not certified. AI features additionally require their normal user configuration;
the installer neither logs in nor provisions credentials.

From the checkout:

```sh
cd frontend && npm ci --include=dev && cd ..
python3.11 tools/linux/vibe_linux.py build --output /path/to/artifacts
```

The archive contains built React assets, backend source, Node runtime source,
lockfiles and the installer. Only tracked runtime inputs and explicitly selected
build files are included, never local private data, `.env`, node_modules or a
venv. Version comes from frontend/package.json; revision and content fingerprint
identify the exact package. Files have stable tar metadata and gzip timestamps;
identical input/build assets produce byte-identical archives. Pinned lockfiles
improve repeatability but the Python lockfile does not contain artifact hashes.

## Install and launch on an allowed Linux machine

Verify the accompanying SHA-256 checksum before extraction. Extract the archive
into a new directory, enter its `vibe-research-*` directory, then:

```sh
python3.11 tools/linux/vibe_linux.py install
```

This downloads dependencies into a new private release directory under
`~/.local/share/vibe-research/releases/`. It prints the exact command to start that
release. Keep the launcher terminal open; Ctrl+C or SIGTERM stops its three
service process groups. Startup failure or one service exiting stops the others.
Occupied ports cause a fail-closed error; the launcher never kills existing
processes or silently changes ports. Concurrent launchers sharing a data directory
are rejected. `run --open-browser` optionally asks the default browser to open the
normal URL, only on machines where that access is allowed.

The installer refuses an existing release directory and never overwrites a prior
installation. A failed install leaves its partial directory for inspection; no
`.installed` marker is created and it cannot be launched. Remove only that failed
release manually before retrying. `install --prefix /your/user-owned/path` chooses
another release root. No PATH, desktop, login, browser or OS settings are changed.

## Data, upgrades and removal

Application data stays in the application's existing `~/.vibe-research` directory,
or an explicitly supplied `VR_DATA_DIR`. Existing browser localStorage remains in
that browser profile. Credentials keep their existing application/CLI locations;
they are never put in the distributable. Terminal logs can contain operational
information; do not publish them without checking for private information.

Install each upgrade side-by-side. Stop the old launcher, back up user data using
the application's existing backup workflow, then run the new release. Do not run
different versions concurrently against the same data. There is no automatic data
migration rollback: a code rollback alone is not a data rollback.

To uninstall, stop the launcher and remove only its release directory. User data,
browser storage and separately managed CLI authentication are intentionally
retained; delete those only if you explicitly intend to lose them.

## Packaging tests from the checkout (no services, browser or providers)

```sh
python3.11 -m unittest discover -s tools/linux -p 'test_*.py' -v
```
