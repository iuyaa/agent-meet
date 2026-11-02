# Skill updates

The invoking host runs `scripts/update.py apply` once before each user-requested
operation, unless the user opts out or pins a version. Resolve it from the
SKILL.md being used, not another discovered install. Use the original project
as command cwd. Re-read SKILL.md after `state=updated` or `state=changed`.

`check` does not replace files. `apply` replaces only this installation when a
newer stable release is published; `--force-check` bypasses the one-hour metadata
cache. There is no daemon and no claim that a skill can wake an idle host.
The current conversation remains the host after an update.

## Published versions and integrity

The checker reads `VERSION` from `iuyaa/agent-meet` main over HTTPS and verifies
that `releases/agent-meet-vVERSION.sha256` exists at tag `vVERSION`. An untagged
source version is not offered as an installable update. Only increasing three-part
stable versions are eligible. A newer local development version is not downgraded.
Each request has a five-second socket timeout; download and expansion sizes are
bounded. It preserves inherited proxy/TLS settings.

For file installations, the updater verifies the tagged ZIP against SHA-256,
rejects unsafe paths, symlink/duplicate/unsupported archive entries, and compares
all package files to `INSTALL-MANIFEST.json`. The checksum checks integrity against
the same official source; it is not a separate publisher signature.

Known text files accept Git/installer CRLF-to-LF normalization when comparing
local hashes; substantive edits and binary changes still defer replacement.
The current manifest is also checked before downloading/staging and immediately
before replacement. Edited/deleted managed files, unknown files conflicting with
new paths or internal managed symlinks defer the update. Extra files and legacy
room data are copied intact. A staged directory replaces the same resolved path;
a symlink to the skill stays a symlink to that path. A failed cutover restores the
old directory. A complete old installation is retained under the cache's backups
directory, outside normal skill discovery. The returned `backup` is authoritative;
if moving a backup to the cache fails, it remains at the reported sibling path.
Do not automatically delete backups, since they may contain old user data.

Clean Git clones on `main` with the official origin fetch the exact release tag
and merge with `--ff-only`; no reset, stash, checkout of another branch, force push
or removal of Git metadata. Detached tags, forks, local edits and divergent branches
are left alone. The result records `previous_commit` for deliberate recovery.

## Running tools, cache and installers

Agent-Meet Python tools acquire a shared installation lease for their process
lifetime. An updater needs an exclusive lease. Retained project-local viewers
preload installed protocol modules and pin static resources, then release their
installation lease. They remain readable across updates; view.py start refreshes
an older viewer version without resetting the room. Legacy viewers whose room
data is inside the skill keep the lease to prevent copying a live database.
Defer busy updates rather than cancel calls or close pages just to force them.
No active room, deadline, native ID, model configuration or authentication is reset.
On Windows the lease uses file sharing handles; on POSIX it uses shared `flock`.
A new tool invoked during replacement reports that the installation is updating
and can be retried afterward.

Cache/lease directories are per resolved installation path:
- Windows: `%LOCALAPPDATA%/agent-meet/INSTALLATION_HASH/`
- macOS: `~/Library/Caches/agent-meet/INSTALLATION_HASH/`
- Linux: `$XDG_CACHE_HOME/agent-meet/INSTALLATION_HASH/`, default `~/.cache/agent-meet/...`

The cache stores version metadata, leases and backups, not model credentials.
A read-only/unavailable cache defers updates; discussions can continue. Broken
metadata caches are ignored. Network/validation/permissions errors return a
`deferred` result; do not loop retries or manufacture a success. Continue an intact
installed skill and briefly explain a relevant deferral. If `can_continue=false`,
report the installation error and backup before attempting more tools.

Skills CLI lock files belong to that installer. Built-in updates do not rewrite
an undocumented external format or update other skills. Installer displays may
need refreshing with the original installer and the same scope/host options.
Pre-v0.12 skills do not know to run the checker; one initial manual/installer
upgrade is required. No instruction here retroactively updates them.
